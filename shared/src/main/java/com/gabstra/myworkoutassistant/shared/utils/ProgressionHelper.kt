package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.lang.Math.pow
import java.util.Collections
import java.util.TreeMap
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.ConcurrentSkipListMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.pow
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

    data class DistributedWorkout(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val totalFatigue: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageFatiguePerSet: Double
    )

    data class WeightExerciseParameters(
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val fatigueFactor: Float,
        val minimumVolume: Double
    )

    data class BodyWeightExerciseParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val repsRange: IntRange,
        val fatigueFactor: Float
    )

    private suspend fun distributeVolume(
        targetTotalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float,
        minimumVolume: Double
    ): DistributedWorkout? {
        val params = WeightExerciseParameters(
            targetTotalVolume = targetTotalVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor,
            minimumVolume = minimumVolume
        )

        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        var validSetCombination = findBestCombination(possibleSets, params.targetTotalVolume,params.minimumVolume)
        if (validSetCombination.isEmpty()) {
            val newPossibleSets = generatePossibleSets(params.copy(percentLoadRange = Pair(0.0,95.0), repsRange =  IntRange(1,30)))
            val newSets = newPossibleSets.filter { it !in possibleSets }
            if(newSets.isNotEmpty()){
                validSetCombination = findBestCombination(newPossibleSets, params.targetTotalVolume,params.minimumVolume)
            }
        }

        return DistributedWorkout(
            sets = validSetCombination,
            totalVolume = validSetCombination.sumOf { it.volume },
            totalFatigue = validSetCombination.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.sumOf { it.fatigue } / validSetCombination.size
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

            if(totalVolume < minimumVolume ) return Double.MIN_VALUE

            val volumeDeviation = abs(totalVolume - targetVolume) / targetVolume

            val list = indices.toList()
            val combinationSets = list.map { validSets[it] }

            // Calculate min/max for reps and weights
            val minReps = combinationSets.minOf { it.reps }
            val maxReps = combinationSets.maxOf { it.reps }

            val repRatio = maxReps.toDouble() / minReps

            val minSetWeight = combinationSets.minOf { it.weight }
            val maxSetWeight = combinationSets.maxOf { it.weight }

            val weightRatio = maxSetWeight / minSetWeight

            val maxFatigue = combinationSets.maxOf { it.fatigue }
            val minFatigue = combinationSets.minOf { it.fatigue }
            val totalFatigue = combinationSets.sumOf { it.fatigue }

            val fatigueRatio = maxFatigue / minFatigue

            val repPenalty = 1.0 - exp(-50.0 * (repRatio - 1.0))
            val weightPenalty = 1.0 - exp(-50.0 * (weightRatio - 1.0))
            val fatiguePenalty = 1.0 - exp(-100.0 * (fatigueRatio - 1.0))

            val consistencyScore = 1.0 - maxOf(repPenalty, weightPenalty, fatiguePenalty)

            // Calculate scores
            val volumeScore = 1.0 / (1.0 + (volumeDeviation * 10))

            return volumeScore * (consistencyScore * consistencyScore)
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

            if (currentCombination.size() == 6) {
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

   /* private suspend fun findBestCombination(
        sets: List<ExerciseSet>,
        targetVolume: Double
    ): List<ExerciseSet> = coroutineScope {
        // Early termination checks
        if (sets.sumOf { it.volume } < targetVolume) {
            Log.d("WorkoutViewModel", "Total volume is less than target")
            return@coroutineScope emptyList()
        }

        val maxWeight = sets.maxOfOrNull { it.weight }?.takeIf { it > 0 } ?: 0.0

        val validSets = sets.sortedWith(compareBy<ExerciseSet> { it.weight }.thenBy { it.reps })

        val mutex = Mutex()
        val exploredStates = ConcurrentHashMap.newKeySet<Long>()
        var bestCombination = emptyList<ExerciseSet>()
        var bestScore = 0.0

        fun encodeState(combination: List<ExerciseSet>): Long {
            var result = 0L
            combination.forEach { set ->
                val index = validSets.indexOf(set)
                result = (result * 31 + index) and Long.MAX_VALUE
            }
            return result
        }

        fun scoreCombination(combination: List<ExerciseSet>): Double {
            val totalVolume = combination.sumOf { it.volume }
            val volumeDeviation = abs(totalVolume - targetVolume) / targetVolume

            // If volume deviation is too high, return worst possible score
            if (volumeDeviation > 0.02) return 0.0

            // Calculate base score components (higher is better)
            val volumeScore = 1.0 / (1.0 + volumeDeviation) // Approaches 1 as deviation approaches 0
            val setScore = 1.0 / combination.size // Fewer sets = higher score
            val fatigueScore = 1.0 / (1.0 + combination.sumOf { it.fatigue })

            // Weight-related scores
            val averageWeight = combination.map { it.weight }.average()
            val weightLevelScore = if (maxWeight > 0) {
                1.0 - (averageWeight / maxWeight)
            } else 0.0

            val weightDifferences = combination.zipWithNext().map { (a, b) ->
                abs(a.weight - b.weight) / a.weight
            }
            val weightConsistencyScore = if (weightDifferences.isEmpty()) 1.0
            else 1.0 / (1.0 + weightDifferences.average())

            // Combine scores with weights to prioritize
            return (volumeScore * 1000 +    // Highest priority: volume match
                    setScore * 100 +        // Second priority: fewer sets
                    fatigueScore * 100 +     // Third priority: lower fatigue
                    weightConsistencyScore * 100 + // Fourth priority: consistent weights
                    weightLevelScore * 100)    // Fifth priority: lower weights
        }

        suspend fun processState(
            currentCombination: List<ExerciseSet>,
        ) {
            val combinationScore = scoreCombination(currentCombination)
            mutex.withLock {
                if (combinationScore > bestScore) {
                    bestScore = combinationScore
                    bestCombination = currentCombination.toList()
                }
            }
        }

        suspend fun backtrack(
            start: Int,
            currentCombination: MutableList<ExerciseSet>,
            scope: CoroutineScope
        ) {
            if(currentCombination.size >= 3){
                processState(currentCombination)
            }
            
            if(currentCombination.size == 6){
                return
            }

            for (i in start until validSets.size) {
                if (!scope.isActive) return

                val nextSet = validSets[i]
                val lastSet = currentCombination.lastOrNull()

                // If this is the first set, process it directly
                if (lastSet == null) {
                    currentCombination += nextSet
                    backtrack(i, currentCombination, scope)
                    currentCombination.removeAt(currentCombination.lastIndex)
                    continue
                }

                // Check if sets are compatible
                //val repsDifference = abs(nextSet.reps - lastSet.reps) / lastSet.reps.toDouble()
                //val weightDifference = abs(nextSet.weight - lastSet.weight) / lastSet.weight

                if (
//                    repsDifference > 0.2 ||
//                    weightDifference > 0.2 ||
//                    nextSet.weight > lastSet.weight ||
                    (nextSet.weight == lastSet.weight && nextSet.reps > lastSet.reps)) {
                    continue
                }

                // Try adding the set and check volume
                currentCombination += nextSet

                val newTotalVolume = currentCombination.sumOf { it.volume }

                if(newTotalVolume > targetVolume){
                    currentCombination.removeAt(currentCombination.lastIndex)
                    continue
                }

                backtrack(i, currentCombination, scope)

                *//*if(currentCombination.size >=3){
                    val desiredVolumePerSet = volumePerSetMap[currentCombination.size]!!

                    val lowerRangeVolumePerSet = desiredVolumePerSet * 0.9
                    val upperRangeVolumePerSet = desiredVolumePerSet * 1.1

                    val currentVolumePerSet = currentCombination.sumOf { it.volume } / currentCombination.size

                    if (currentVolumePerSet in lowerRangeVolumePerSet..upperRangeVolumePerSet) {
                        backtrack(i, currentCombination, scope)
                    }
                }else{
                    backtrack(i, currentCombination, scope)
                }
*//*
                currentCombination.removeAt(currentCombination.lastIndex)
            }
        }

        // Determine optimal number of parallel jobs based on available memory and processors
        val runtime = Runtime.getRuntime()
        val maxMemoryBytes = runtime.maxMemory()  // Maximum memory JVM will attempt to use
        val usedMemoryBytes = runtime.totalMemory() - runtime.freeMemory()  // Currently used memory
        val availableMemoryBytes = maxMemoryBytes - usedMemoryBytes

        // Reserve 10% of available memory for overhead and other operations
        val safeMemoryBytes = availableMemoryBytes * 0.9

        // Estimate memory needed per job (conservative estimate - 1MB)
        val estimatedBytesPerJob = 1 * 1024 * 1024

        val maxJobsByMemory = (safeMemoryBytes / estimatedBytesPerJob).toInt()
        val maxJobsByCPU = runtime.availableProcessors()

        // Use whichever limit is smaller to be safe
        val maxParallelJobs = minOf(maxJobsByMemory, maxJobsByCPU).coerceAtLeast(1)

        // Create job groups to process in batches
        val branches = maxOf(1, validSets.size / maxParallelJobs)

        val supervisorJob = SupervisorJob()
        val scope = CoroutineScope(Dispatchers.IO + supervisorJob)
        val allJobs = mutableListOf<Job>()

        try {
            for(index in 0 until branches) {
                val job = scope.launch {
                    backtrack(
                        start = index,
                        currentCombination = mutableListOf(),
                        scope = scope  // Pass parent scope instead of coroutine scope
                    )
                }
                allJobs.add(job)
            }

            // Simple timeout handling
            if (withTimeoutOrNull(30_000) { allJobs.joinAll() } == null) {
                // Timeout occurred
                supervisorJob.cancel()
            }
        } finally {
            // Ensure everything is cleaned up
            runBlocking {
                supervisorJob.cancelAndJoin()
            }
        }

        bestCombination.reversed()
    }*/

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

    data class SetCombination(
        val sets: List<ExerciseSet>,
        val totalFatigue: Double,
        val totalVolume: Double,
        val averageFatiguePerSet: Double
    )

    private fun findValidSetCombination(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double
    ): SetCombination? {
        if (possibleSets.isEmpty()) return null

        // Pre-filter and sort possible sets by weight and then reps
        val filteredSets = possibleSets
            .sortedWith(compareByDescending<ExerciseSet> { it.weight }
                .thenByDescending { it.reps })
            .filter { it.volume <= targetVolume / targetSets * 1.2 }
            .take(10)

        data class SearchState(
            val remainingSets: Int,
            val remainingVolume: Double,
            val currentSets: List<ExerciseSet>,
            val currentFatigue: Double,
            val lastWeight: Double? = null
        )

        val queue = ArrayDeque<SearchState>()
        var bestCombination: SetCombination? = null
        var closestVolumeGap = Double.MAX_VALUE
        var bestFatigue = Double.MAX_VALUE

        queue.add(
            SearchState(
                remainingSets = targetSets,
                remainingVolume = targetVolume,
                currentSets = emptyList(),
                currentFatigue = 0.0
            )
        )

        while (queue.isNotEmpty()) {
            val state = queue.removeFirst()

            // Complete combination found
            if (state.currentSets.size == targetSets) {
                val totalVolume = state.currentSets.sumOf { it.volume }
                val volumeGap = targetVolume - totalVolume

                // Only consider solutions that don't exceed target volume and have proper weight progression
                if (volumeGap >= 0 && isWeightProgressionValid(state.currentSets)) {
                    // Update best combination if:
                    // 1. This combination is closer to target volume, or
                    // 2. Equal volume distance but has less fatigue
                    if (volumeGap < closestVolumeGap ||
                        (volumeGap == closestVolumeGap && state.currentFatigue < bestFatigue)
                    ) {
                        closestVolumeGap = volumeGap
                        bestFatigue = state.currentFatigue
                        bestCombination = SetCombination(
                            sets = state.currentSets,
                            totalFatigue = state.currentFatigue,
                            totalVolume = totalVolume,
                            averageFatiguePerSet = state.currentFatigue / targetSets
                        )
                    }
                }
                continue
            }

            val currentVolume = state.currentSets.sumOf { it.volume }
            val volumeGap = targetVolume - currentVolume

            // Skip if we've exceeded target volume
            if (volumeGap < 0) {
                continue
            }

            // Get valid next sets that maintain weight progression
            val validNextSets = filteredSets
                .filter { set ->
                    // Weight must be equal or less than previous set
                    val isWeightValid = if (state.lastWeight != null) {
                        set.weight <= state.lastWeight
                    } else true

                    // Total volume must not exceed target
                    val isVolumeValid = (currentVolume + set.volume) <= targetVolume

                    isWeightValid && isVolumeValid
                }

            // Add new states to queue
            for (set in validNextSets) {
                // Calculate if this path could possibly get close enough to target
                val remainingSets = state.remainingSets - 1
                val remainingVolumeNeeded = targetVolume - (currentVolume + set.volume)
                val isPathViable = if (remainingSets > 0) {
                    // Check if we can possibly reach target with remaining sets
                    val maxVolumePerRemainingSet = validNextSets
                        .filter { it.weight <= set.weight }
                        .maxOfOrNull { it.volume } ?: 0.0
                    remainingVolumeNeeded <= (remainingSets * maxVolumePerRemainingSet)
                } else true

                if (isPathViable) {
                    queue.add(
                        SearchState(
                            remainingSets = remainingSets,
                            remainingVolume = state.remainingVolume - set.volume,
                            currentSets = state.currentSets + set,
                            currentFatigue = state.currentFatigue + set.fatigue,
                            lastWeight = set.weight
                        )
                    )
                }
            }

            // Manage queue size
            if (queue.size > 1000) {
                val sortedQueue = queue.sortedWith(compareBy(
                    // Sort by how close they could get to target volume
                    { state ->
                        val currentStateVolume = state.currentSets.sumOf { it.volume }
                        kotlin.math.abs(targetVolume - currentStateVolume)
                    },
                    { it.currentFatigue }
                ))
                queue.clear()
                queue.addAll(sortedQueue.take(500))
            }
        }

        return bestCombination
    }

    // Helper function to verify weight progression
    private fun isWeightProgressionValid(sets: List<ExerciseSet>): Boolean {
        for (i in 1 until sets.size) {
            if (sets[i].weight > sets[i - 1].weight) {
                return false
            }
        }
        return true
    }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
        fatigueFactor: Float
    ): ExerciseSet {
        val volume = weight * reps
        val percentLoad = (weight / oneRepMax) * 100

        // Calculate intensity multiplier based on proximity to 1RM
        // Exponential increase as weight gets closer to 1RM
        val intensityMultiplier = kotlin.math.exp(
            1.5 * (percentLoad / 100.0) * (percentLoad / 100.0)
        )

        // Rep multiplier - higher reps are exponentially more fatiguing
        val repMultiplier = 1 + ln(1.0 + reps)

        // Enhanced fatigue calculation that maintains original parameter influence
        // while incorporating intensity and rep effects
        val fatigue = volume * (1 + fatigueFactor * ln(
            1 + (intensityMultiplier * repMultiplier * percentLoad * reps / 10000)
        ))

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

        if(percentageIncrease >= 1){
            val minimumRequiredVolume = currentVolume * (1 + (percentageIncrease / 100))

            val solution = distributeVolume(
                targetTotalVolume = minimumRequiredVolume,
                oneRepMax = oneRepMax,
                availableWeights = availableWeights,
                percentLoadRange = percentLoadRange,
                repsRange = repsRange,
                fatigueFactor = fatigueFactor,
                minimumVolume = currentVolume * 1.01
            )

            if (solution != null) {
                return solution
            }
        }

        val noIncreaseSolution = distributeVolume(
            targetTotalVolume = currentVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor,
            minimumVolume = currentVolume
        )

        return noIncreaseSolution
    }

    private fun createBodyWeightSet(
        reps: Int,
        fatigueFactor: Float
    ): ExerciseSet {
        val volume = reps.toDouble()
        // For bodyweight exercises, we use a simplified fatigue calculation
        // since we don't have percentage load to factor in
        val fatigue = volume * (1 + fatigueFactor * ln(1.0 + reps))

        return ExerciseSet(
            weight = 1.0, // Use 1.0 as a multiplier for bodyweight
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = 100.0, // Constant since it's always bodyweight
        )
    }

    private suspend fun findBodyWeightSolution(params: BodyWeightExerciseParameters): DistributedWorkout? {
        var possibleSets = generatePossibleBodyWeightSets(params)

        if (possibleSets.isEmpty()) return null

        // Find valid combination of sets
        val validSetCombinations = findAllValidBodyWeightSetCombinations(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
        )

        val validSetCombination =
            validSetCombinations.sortedBy { it.totalFatigue }.minByOrNull { it.totalFatigue }
                ?: return null

        return DistributedWorkout(
            sets = validSetCombination.sets,
            totalVolume = validSetCombination.sets.sumOf { it.volume },
            totalFatigue = validSetCombination.sets.sumOf { it.fatigue },
            usedOneRepMax = 1.0, // Not applicable for bodyweight
            maxRepsUsed = validSetCombination.sets.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.averageFatiguePerSet
        )
    }

    private suspend fun generatePossibleBodyWeightSets(
        params: BodyWeightExerciseParameters
    ): List<ExerciseSet> = coroutineScope {
        params.repsRange.map { reps ->
            createBodyWeightSet(
                reps = reps,
                fatigueFactor = params.fatigueFactor
            )
        }
    }

    private fun findAllValidBodyWeightSetCombinations(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double,
        maxResults: Int = 10
    ): List<SetCombination> {
        val validSets = possibleSets

        if (validSets.isEmpty()) return emptyList()



        fun getValidSetsForRemaining(
            remainingSets: Int,
            remainingVolume: Double,
            previousFatigue: Double
        ): List<ExerciseSet> {
            val targetVolumePerSet = remainingVolume / remainingSets
            val minVolumePerSet = targetVolumePerSet * 0.8
            val maxVolumePerSet = targetVolumePerSet * 1.2

            val filteredSets = validSets.filter {
                it.volume in minVolumePerSet..maxVolumePerSet &&
                        it.fatigue <= previousFatigue
            }

            return filteredSets.sortedWith(
                compareBy(
                    { kotlin.math.abs(it.volume - targetVolumePerSet) },
                    { it.fatigue })
            )
        }

        val results = mutableListOf<SetCombination>()
        val uniqueCombinations = mutableSetOf<List<ExerciseSet>>()

        fun search(
            remainingSets: Int,
            remainingVolume: Double,
            currentSets: List<ExerciseSet>,
            previousFatigue: Double = Double.MAX_VALUE,
            currentFatigue: Double = currentSets.sumOf { it.fatigue }
        ): Boolean {  // Return true if we should stop searching
            if (results.size >= maxResults) return true

            if (currentSets.size == targetSets) {
                val totalVolume = targetVolume - remainingVolume
                if (totalVolume >= targetVolume && totalVolume <= targetVolume * 1.1) {
                    if (uniqueCombinations.add(currentSets)) {
                        results.add(
                            SetCombination(
                                sets = currentSets,
                                totalFatigue = currentFatigue,
                                totalVolume = totalVolume,
                                averageFatiguePerSet = currentFatigue / targetSets
                            )
                        )
                    }
                    return results.size >= maxResults
                }
                return false
            }

            // Early pruning: check if minimum possible volume is achievable
            val validSetsForRemaining = getValidSetsForRemaining(
                remainingSets = remainingSets,
                remainingVolume = remainingVolume,
                previousFatigue = previousFatigue
            )

            if (validSetsForRemaining.isEmpty()) return false

            val minPossibleVolumePerSet = validSetsForRemaining.minOf { it.volume }
            if (minPossibleVolumePerSet * remainingSets < remainingVolume * 0.5) {
                return false
            }

            // Try each valid set
            for (set in validSetsForRemaining) {
                val newRemainingVolume = remainingVolume - set.volume

                // Skip if total volume would be too high
                if (targetVolume - newRemainingVolume > targetVolume * 1.1) continue
                if (newRemainingVolume < 0) continue

                val shouldStop = search(
                    remainingSets = remainingSets - 1,
                    remainingVolume = newRemainingVolume,
                    currentSets = currentSets + set,
                    previousFatigue = set.fatigue,
                    currentFatigue = currentFatigue + set.fatigue
                )

                if (shouldStop) return true
            }

            return false
        }

        search(
            remainingSets = targetSets,
            remainingVolume = targetVolume,
            currentSets = emptyList()
        )

        return results
    }

    suspend fun distributeBodyWeightVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        percentageIncrease: Float,
        repsRange: IntRange,
        fatigueFactor: Float
    ): Pair<DistributedWorkout?, Boolean> {
        if (percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease / 100))
        val maximumRequiredVolume = minimumRequiredVolume * 1.05

        val baseParams = BodyWeightExerciseParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        val solution = findBodyWeightSolution(baseParams)
        if (solution != null && solution.totalVolume >= minimumRequiredVolume && solution.totalVolume <= maximumRequiredVolume) {
            return Pair(solution, false)
        }

        val increasedSetSolution =
            findBodyWeightSolution(baseParams.copy(numberOfSets = numberOfSets + 1))

        if (increasedSetSolution != null && increasedSetSolution.totalVolume >= minimumRequiredVolume && increasedSetSolution.totalVolume <= maximumRequiredVolume) {
            return Pair(increasedSetSolution, false)
        }

        return Pair(null, true)
    }
}
