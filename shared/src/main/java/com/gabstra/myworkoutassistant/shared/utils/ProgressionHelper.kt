package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
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
        val minimumVolume: Double
    )

    private suspend fun distributeVolume(
        params: WeightExerciseParameters,
    ): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        var validSetCombination = findBestCombinationVariant(possibleSets, params.targetTotalVolume,params.minimumVolume)
        if (validSetCombination.isEmpty()) {
            val newPossibleSets = generatePossibleSets(params.copy(percentLoadRange = Pair(40.0,93.0), repsRange = IntRange(3,30)))
            val newSets = newPossibleSets.filter { it !in possibleSets }
            if (newSets.isEmpty()) return null
            validSetCombination = findBestCombinationVariant(newPossibleSets, params.targetTotalVolume,params.minimumVolume)
        }

        if(validSetCombination.isEmpty()) return null

        val totalVolume = validSetCombination.sumOf { it.volume }



        return DistributedWorkout(
            sets = validSetCombination,
            totalVolume = validSetCombination.sumOf { it.volume },
            totalFatigue = validSetCombination.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.sumOf { it.fatigue } / validSetCombination.size,
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100
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

        val validSets = sets.filter { it.volume < targetVolume }.sortedWith(compareBy<ExerciseSet> { it.weight }.thenByDescending { it.reps })

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
            if(totalVolume < minimumVolume) return Double.MIN_VALUE

            val combinationSets = indices.toList().map { validSets[it] }

            // Volume score calculation
            val volumeDeviation = abs(totalVolume - targetVolume) / targetVolume
            val volumeScore = 1.0 / (1.0 + volumeDeviation * 10)

            // Ratio calculations
            val repRatio = combinationSets.maxOf { it.reps }.toDouble() / combinationSets.minOf { it.reps }
            val weightRatio = combinationSets.maxOf { it.weight } / combinationSets.minOf { it.weight }
            val fatigueRatio = combinationSets.maxOf { it.fatigue } / combinationSets.minOf { it.fatigue }

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

            if(remainingVolume < 0 || totalVolume > targetVolume) return

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
            val minPossibleVolume = remainingVolume - (maxPossibleSetVolume * (6 - currentCombination.size()))
            if (minPossibleVolume > 0) return

            for (i in start until validSets.size) {
                if (!scope.isActive) return

                val nextSet = validSets[i]

                if (remainingVolume - nextSet.volume < 0) {
                    continue
                }

                if (currentCombination.size() > 0) {
                    val lastSet = validSets[currentCombination.toList()[currentCombination.size() - 1]]
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

            while(currentMaxJobs == 0){
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

    // Use value class to reduce memory overhead
    @JvmInline
    value class SearchResult(val pair: Pair<List<ExerciseSet>, Double>) {
        val combination: List<ExerciseSet> get() = pair.first
        val score: Double get() = pair.second

        companion object {
            val EMPTY = SearchResult(emptyList<ExerciseSet>() to Double.MIN_VALUE)
        }
    }

    private suspend fun findBestCombinationVariant(
        sets: List<ExerciseSet>,
        targetVolume: Double,
        minimumVolume: Double,
    ) = coroutineScope {
        val sortedSets = sets
            .filter {
                when {
                    it.volume > targetVolume -> false
                    it.volume * 3 > targetVolume -> false
                    it.volume * 5 < minimumVolume  -> false
                    else -> true
                }
            }
            .sortedByDescending { it.volume }
            .toList()

        val EXP_50 = exp(-50.0)
        val EXP_HALF = exp(-0.5)

        fun scoreCombination(setCombo: List<ExerciseSet>): Double {
            val totalVolume = setCombo.sumOf { it.volume }

            val volumeDeviation = abs(totalVolume - targetVolume) / targetVolume
            val volumeScore = 1.0 / (1.0 + volumeDeviation * 10)

            var maxReps = Double.MIN_VALUE
            var minReps = Double.MAX_VALUE
            var maxWeight = Double.MIN_VALUE
            var minWeight = Double.MAX_VALUE
            var maxFatigue = Double.MIN_VALUE
            var minFatigue = Double.MAX_VALUE
            var totalFatigue = 0.0

            setCombo.forEach { set ->
                // Reps
                maxReps = maxOf(maxReps, set.reps.toDouble())
                minReps = minOf(minReps, set.reps.toDouble())
                // Weight
                maxWeight = maxOf(maxWeight, set.weight)
                minWeight = minOf(minWeight, set.weight)
                // Fatigue
                maxFatigue = maxOf(maxFatigue, set.fatigue)
                minFatigue = minOf(minFatigue, set.fatigue)
                totalFatigue += set.fatigue
            }

            val repRatio = maxReps / minReps
            val weightRatio = maxWeight / minWeight
            val fatigueRatio = maxFatigue / minFatigue


            val repPenalty = 1.0 - EXP_50.pow(repRatio - 1.0)
            val weightPenalty = 1.0 - EXP_50.pow(weightRatio - 1.0)
            val fatiguePenalty = 1.0 - EXP_50.pow(fatigueRatio - 1.0)

            val consistencyScore = (1.0 - maxOf(repPenalty, weightPenalty, fatiguePenalty)).pow(2)

            val averageFatigue = totalFatigue / setCombo.size
            val fatigueEfficiencyScore = (1.0 / (1.0 + averageFatigue * 5)).pow(2)

            val combinationSetsPenalty = 1.0 - EXP_50.pow(setCombo.size - 1)
            val setSizeScore = 1.0 - combinationSetsPenalty

            return volumeScore * consistencyScore * fatigueEfficiencyScore * setSizeScore
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int): SearchResult = withContext(Dispatchers.Default) {
            val MAX_SETS = 5
            val MIN_VALID_SETS = 3

            data class SearchState(
                val depth: Int,
                val startIdx: Int,
            )

            val currentCombo = arrayOfNulls<ExerciseSet>(MAX_SETS)
            val stack = ArrayDeque<SearchState>(MAX_SETS + 1)
            val volumes = DoubleArray(MAX_SETS + 1) // +1 because we store cumulative volumes
            var bestScore = Double.NEGATIVE_INFINITY
            lateinit var bestCombination: List<ExerciseSet>

            fun isValidNextSet(previousSet: ExerciseSet, nextSet: ExerciseSet): Boolean {
                return previousSet.weight > nextSet.weight ||
                        (previousSet.weight == nextSet.weight && previousSet.reps >= nextSet.reps)
            }

            // Process each starting set in the chunk
            for (firstSetIdx in startIdx until endIdx) {
                stack.clear()
                stack.addLast(SearchState(0, firstSetIdx))

                while (stack.isNotEmpty()) {
                    val currentState = stack.removeLast()
                    val depth = currentState.depth
                    val i = currentState.startIdx

                    val set = sortedSets[i]
                    val newVolume = volumes[depth] + set.volume

                    // Update state
                    currentCombo[depth] = set
                    volumes[depth + 1] = newVolume

                    if (newVolume > targetVolume) {
                        continue
                    }

                    // Score if we have enough sets
                    val currentSize = depth + 1
                    if (currentSize >= MIN_VALID_SETS && newVolume >= minimumVolume) {
                        val currentList = currentCombo.slice(0..depth).filterNotNull()
                        val score = scoreCombination(currentList)
                        if (score > bestScore) {
                            bestScore = score
                            bestCombination = currentList
                        }
                    }

                    if (depth > 0 && isValidNextSet(currentCombo[depth - 1]!!, set) && i + 1 < sortedSets.size) {
                        stack.addLast(currentState.copy(startIdx = i + 1))
                    }

                    val remainingSets = MAX_SETS - (depth + 1)
                    if (remainingSets > 0) {
                        val remainingMaxVolume = remainingSets * sortedSets[i].volume
                        val canReachMinimum = newVolume + remainingMaxVolume >= minimumVolume

                       if (canReachMinimum) {
                            stack.addLast(SearchState(depth + 1, i))
                       }
                    }
                }
            }

            if (bestScore == Double.NEGATIVE_INFINITY) SearchResult.EMPTY
            else SearchResult(bestCombination to bestScore)
        }

        val numThreads = minOf(
            Runtime.getRuntime().availableProcessors().coerceAtLeast(1),
            sortedSets.size
        )
        val chunkSize = (sortedSets.size + numThreads - 1) / numThreads

        (0 until numThreads)
            .asSequence()
            .map { threadIdx ->
                async(Dispatchers.IO) {
                    val startIdx = threadIdx * chunkSize
                    val endIdx = minOf(startIdx + chunkSize, sortedSets.size)
                    if (startIdx < endIdx) searchChunk(startIdx, endIdx)
                    else SearchResult.EMPTY
                }
            }
            .toList()
            .awaitAll()
            .maxByOrNull { it.score }
            ?.combination ?: emptyList()
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100)
            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)
            val weightRange = params.availableWeights.filter { it in minWeight..maxWeight }
            
            val setsDeferred = weightRange.map { weight ->
                async(Dispatchers.IO) {
                    params.repsRange.map { reps ->
                        createSet(
                            weight = weight,
                            reps = reps,
                            oneRepMax = params.oneRepMax,
                            fatigueFactor = params.fatigueFactor
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
        fatigueFactor: Float
    ): ExerciseSet {
        val volume = weight * reps
        val percentLoad = (weight / oneRepMax) * 100
        val relativeIntensity = weight / oneRepMax

        val intensityMultiplier = exp(2.0 * relativeIntensity)
        val repMultiplier = 1 + ln(1.0 + reps)
        val fatigue = volume * fatigueFactor * (intensityMultiplier * repMultiplier) / 100

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
        fatigueFactor: Float
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
            originalVolume = currentVolume
        )

        if(percentageIncrease >= 1){
            val minimumRequiredVolume = currentVolume * (1 + (percentageIncrease / 100))
            val standardSolution = distributeVolume(params.copy(targetTotalVolume = minimumRequiredVolume, minimumVolume = currentVolume*1.01))
            if (standardSolution != null) {
                return standardSolution
            }
        }

        val noIncreaseSolution = distributeVolume(params)

        return noIncreaseSolution
    }
}
