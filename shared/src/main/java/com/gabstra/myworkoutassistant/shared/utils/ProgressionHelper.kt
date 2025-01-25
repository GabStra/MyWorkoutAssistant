package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.roundToInt

object ProgressionHelper {
    enum class ExerciseCategory {
        STRENGTH,
        HYPERTROPHY,
        ENDURANCE;

        companion object {
            fun fromString(type: String):  ExerciseCategory? {
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
    )

    data class ExerciseData(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageIntensity: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
        val isDeloading : Boolean
    )

    data class WeightExerciseParameters(
        val originalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val minSets: Int,
        val maxSets: Int,
        val isDeload : Boolean,
        val currentSets : List<GenericSet>
    )

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseData? {
        val possibleSets = generatePossibleSets(params)

        ///val sets = possibleSets.joinToString { it ->"(${it.weight} kg x ${it.reps})" }

        Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.size}")
        if (possibleSets.isEmpty()){
            //Log.d("WorkoutViewModel", "No sets available")
            return null
        }

        val currentVolume = params.currentSets.sumOf { it.weight * it.reps }
        val averageIntensity = params.currentSets.map { it.weight }.average()


        val validSetCombination = findBestProgressions(
            possibleSets,
            params.minSets,
            params.maxSets,
            currentVolume,
            averageIntensity
        )
        if (validSetCombination.isEmpty()){
            //Log.d("WorkoutViewModel", "No valid combination found")
            return null
        }

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseData(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100,
            averageIntensity = validSetCombination.map { it.percentLoad }.average(),
            originalVolume = params.originalVolume,
            isDeloading = params.isDeload
        )
    }

    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
        minVolume: Double,
        minIntensity: Double
    ) = coroutineScope {
        require(minSets > 0)
        require(minSets <= maxSets)

        // Thread-safe variables using atomic references and mutex
        val bestComboRef = AtomicReference<List<ExerciseSet>>(emptyList())
        val bestScore = AtomicReference(Double.MAX_VALUE)

        val sortedSets = sets
            .filter { it.volume >= minVolume / maxSets }
            .sortedWith(
                compareByDescending<ExerciseSet> { it.weight }
                    .thenByDescending { it.reps }
            )
            .toList()

        Log.d("WorkoutViewModel", "Sets after filtering: ${sortedSets.size}")

        if (sortedSets.size < minSets) {
            return@coroutineScope emptyList()
        }

        fun calculateScore(
            currentCombo: List<ExerciseSet>,
        ): Double {
            val currentTotalVolume = currentCombo.sumOf { it.volume }
            val currentAverageIntensity = currentCombo.map { it.weight }.average()
            val intensityVariation = (currentCombo.maxOf { it.weight } - currentCombo.minOf { it.weight }) + 1
            if(currentTotalVolume < minVolume || currentAverageIntensity <= minIntensity) return Double.MAX_VALUE

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
            val setsMinWeight = params.currentSets.maxOf { it.weight } * 0.9
            val setsMaxWeight = params.currentSets.maxOf { it.weight } * 1.05

            Log.d("WorkoutViewModel", "Sets min weight: $setsMinWeight kg - Sets max weight: $setsMaxWeight kg")

            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)

            val desiredMaxWeight = minOf(maxWeight, setsMaxWeight)

            val availableWeights = params.availableWeights.filter { it in setsMinWeight..desiredMaxWeight }
            val averageIntensity = params.currentSets.map { it.weight }.average()

            val minimumViableWeight = calculateMinWeight(
                weights = availableWeights,
                k = params.maxSets,
                desiredAverage = averageIntensity
            ) ?: setsMinWeight

            val desiredMinWeight = maxOf(minimumViableWeight, setsMinWeight)

            Log.d("WorkoutViewModel", "Desired min weight: $desiredMinWeight kg - Desired max weight: $desiredMaxWeight kg")

            val weightRange =  params.availableWeights.filter { it in desiredMinWeight..desiredMaxWeight }

            val setsDeferred = weightRange.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).roundToInt() + 1

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

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            percentLoad = percentLoad,
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
        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            originalVolume = totalVolume,
            minSets = 3,
            maxSets = 5,
            isDeload = false,
            currentSets = currentSets
        )

        return getProgression(baseParams)
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
