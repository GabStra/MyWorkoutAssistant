package com.gabstra.myworkoutassistant.shared.utils

import kotlinx.coroutines.*
import java.util.concurrent.atomic.AtomicReference
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
        val averageIntensity: Double,
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
            params.averageLoad,
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
                params.averageLoad,
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
            averageIntensity = validSetCombination.map { it.percentLoad }.average(),
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
        minIntensity: Double,
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
            val intensityVariation = (currentCombo.maxOf { it.weight } - currentCombo.minOf { it.weight }) + 1
            val validationResult = validationRules(currentTotalVolume, currentAverageIntensity)
            if (validationResult.shouldReturn) {
                return validationResult.returnValue
            }

            return currentTotalVolume * currentAverageIntensity * intensityVariation
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

                    val validSets = sortedSets.filter { ((lastSet.weight > it.weight) ||
                            (lastSet.weight == it.weight && lastSet.reps >= it.reps)) && it.volume <= lastSet.volume*1.2}

                    val maxVolume = validSets.maxOf { it.volume }
                    val maxPossibleVolume = currentVolume +
                            (maxSets - currentCombo.size) * maxVolume
                    if (maxPossibleVolume < minVolume) return

                    val maxWeight = validSets.maxOf { it.weight }
                    val maxPossibleIntensity = (currentCombo.sumOf { it.weight } +
                            maxWeight * (maxSets - currentCombo.size)) / maxSets

                    if (maxPossibleIntensity < minIntensity) return

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

    private fun calculateMinWeight(
        weights: List<Double>,
        k: Int,
        desiredAverage: Double
    ): Double? {
        val targetSum = k * desiredAverage
        if (k <= 0 || weights.isEmpty()) return null

        // dp[i] will map "sum" -> "minimum weight in some subset of size i with that sum"
        // If dp[i][sum] = null, it means no subset of size i exists with that sum.
        val dp = List(k + 1) { HashMap<Double, Double?>() }

        // Base case: dp[0][0.0] = Double.POSITIVE_INFINITY
        // (signals a valid subset of size 0 & sum 0, but "no actual min weight" yet)
        dp[0][0.0] = Double.POSITIVE_INFINITY

        for (i in 1..k) {
            for ((sumVal, minW) in dp[i - 1]) {
                if (minW == null) continue
                // Try adding each weight w (unbounded usage)
                for (w in weights) {
                    val newSum = sumVal + w
                    // Minimum weight in the new subset is the smaller of w and previous subset's min
                    val newMinWeight = kotlin.math.min(minW, w)

                    // Update dp[i][newSum] if:
                    //   - it is null, or
                    //   - we found a smaller "minimum weight" for that sum
                    val current = dp[i][newSum]
                    if (current == null || newMinWeight < current) {
                        dp[i][newSum] = newMinWeight
                    }
                }
            }
        }

        // Look up dp[k][targetSum]
        // If it's null, no subset of size k sums exactly to targetSum
        return dp[k][targetSum]
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
                    index in (closestWeightIndex - 2)..(closestWeightIndex + 2)
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
