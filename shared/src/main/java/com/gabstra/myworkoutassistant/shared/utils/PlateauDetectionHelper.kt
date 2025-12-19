package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.OneRM
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.UUID
import kotlin.math.abs

object PlateauDetectionHelper {
    // -----------------------------
    // CONFIG (TUNE THESE)
    // -----------------------------
    private const val DEFAULT_BIN_SIZE = 0.25    // kg; fallback BIN_SIZE when equipment unavailable
    private const val REP_TOL_BASE = 2            // base allowed rep drop when increasing weight
    private const val REP_TOL_PERCENT = 0.15      // percentage of reps for flexible tolerance (15%)
    private const val MIN_VOLUME_DELTA = 2        // extra total reps to count as progress
    private const val WINDOW_SESS = 3             // how many recent sessions to inspect for plateau
    private const val MIN_SESS_FOR_PLAT = 4       // minimal sessions before calling plateau
    private const val RECENT_BASELINE_WINDOW = 10 // how many recent sessions to use for baseline comparison
    private const val MAX_DAYS_FOR_PLATEAU_DETECTION = 30L // only consider data from at most 30 days earlier
    
    // Edge case handling constants
    private const val MAX_DAYS_BETWEEN_SESSIONS = 60L      // Reset baseline if gap > 60 days
    private const val WEIGHT_DROP_THRESHOLD = 0.20         // 20% weight drop triggers baseline reset
    private const val MIN_BIN_SIZE = 0.1                    // Minimum bin size in kg
    private const val LOW_REP_THRESHOLD = 3                // Reps ≤ 3 get stricter tolerance
    
    // Cache for BIN_SIZE per equipment
    private val binSizeCache: MutableMap<UUID, Double> = mutableMapOf()

    // -----------------------------
    // DATA CLASSES
    // -----------------------------
    data class Session(
        val id: UUID,              // workoutHistoryId
        val date: LocalDate,
        val sets: List<SimpleSet>, // weight and reps for working sets only
        val isDeload: Boolean = false, // true if this session was marked as DELOAD
        val isBodyweightExercise: Boolean = false, // true if this session contains bodyweight exercises
        val externalWeights: Map<SimpleSet, Double> = emptyMap() // For bodyweight exercises: SimpleSet -> external weight (additionalWeight)
    )

    // -----------------------------
    // HELPERS
    // -----------------------------
    
    /**
     * Calculates GCD (Greatest Common Divisor) of two floating-point numbers.
     * Uses Euclidean algorithm with tolerance for floating-point precision.
     * For better precision with weight values (typically 1-2 decimal places),
     * we scale to integers, compute GCD, then scale back.
     */
    private fun gcd(a: Double, b: Double, tolerance: Double = 1e-6): Double {
        val absA = abs(a)
        val absB = abs(b)
        
        if (absB < tolerance) return absA
        if (absA < tolerance) return absB
        
        // Scale to integers by multiplying by 10000 (handles up to 4 decimal places)
        // This avoids floating-point precision issues with modulo
        val scale = 10000.0
        val scaledA = (absA * scale).toLong()
        val scaledB = (absB * scale).toLong()
        
        // Use integer GCD
        val gcdInt = gcdInt(scaledA, scaledB)
        
        // Scale back
        return gcdInt / scale
    }
    
    /**
     * Integer GCD using Euclidean algorithm.
     */
    private fun gcdInt(a: Long, b: Long): Long {
        val absA = if (a < 0) -a else a
        return if (b == 0L) absA else gcdInt(b, absA % b)
    }
    
    /**
     * Calculates GCD of a list of numbers.
     */
    private fun gcdOfList(numbers: List<Double>): Double {
        if (numbers.isEmpty()) return DEFAULT_BIN_SIZE
        if (numbers.size == 1) return abs(numbers[0])
        
        var result = abs(numbers[0])
        for (i in 1 until numbers.size) {
            result = gcd(result, abs(numbers[i]))
            if (result < 1e-9) return DEFAULT_BIN_SIZE // Avoid division by zero
        }
        return result
    }
    
    /**
     * Calculates BIN_SIZE from equipment's achievable weight combinations.
     * Uses GCD of all weight differences between consecutive achievable weights.
     * Caches the result per equipment ID.
     */
    fun calculateBinSize(equipment: WeightLoadedEquipment?): Double {
        if (equipment == null) {
            return DEFAULT_BIN_SIZE
        }
        
        // Check cache first
        binSizeCache[equipment.id]?.let {
            return it 
        }

        try {
            // Get all achievable weights
            val weights = equipment.getWeightsCombinations().sorted()

            // Need at least 2 weights to calculate differences
            if (weights.size < 2) {
                val binSize = DEFAULT_BIN_SIZE
                binSizeCache[equipment.id] = binSize
                return binSize
            }
            
            // Calculate differences between consecutive weights
            val differences = mutableListOf<Double>()
            val maxWeight = weights.maxOrNull() ?: 0.0
            for (i in 0 until weights.size - 1) {
                val diff = weights[i + 1] - weights[i]
                // Filter out differences that are too small (within tolerance)
                // This prevents floating-point noise from affecting GCD calculation
                if (diff > 1e-6) { // Only consider meaningful positive differences
                    differences.add(diff)
                }
            }

            // If no valid differences, use default
            if (differences.isEmpty()) {
                val binSize = maxOf(DEFAULT_BIN_SIZE, MIN_BIN_SIZE)
                binSizeCache[equipment.id] = binSize
                return binSize
            }
            
            // Calculate GCD of all differences
            val binSize = gcdOfList(differences)

            // Ensure BIN_SIZE is at least MIN_BIN_SIZE and reasonable
            // Also ensure it's at least 0.01% of max weight if max weight is very large
            val minBinSizeFromMaxWeight = if (maxWeight > 0) maxWeight * 0.0001 else MIN_BIN_SIZE
            val finalBinSize = maxOf(
                if (binSize > 1e-9) binSize else DEFAULT_BIN_SIZE,
                MIN_BIN_SIZE,
                minBinSizeFromMaxWeight
            )

            // Cache the result
            binSizeCache[equipment.id] = finalBinSize
            return finalBinSize
        } catch (e: Exception) {
            // If calculation fails, use default
            val binSize = DEFAULT_BIN_SIZE
            binSizeCache[equipment.id] = binSize
            return binSize
        }
    }
    
    private fun weightBin(weight: Double, binSize: Double): Double {
        val bin = kotlin.math.round(weight / binSize) * binSize
        return bin
    }

    /**
     * Calculates flexible rep tolerance based on rep count.
     * Uses percentage-based tolerance with a minimum base value.
     * For very low rep counts (≤3), uses stricter tolerance to prevent
     * counting failed lifts (e.g., 1→0 rep) as improvements.
     */
    private fun calculateRepTolerance(reps: Int): Int {
        if (reps <= LOW_REP_THRESHOLD) {
            // For very low rep counts, use stricter tolerance
            // For 1 rep: 0 tolerance (no drop allowed - 1→0 is failure)
            // For 2 reps: 1 tolerance (allow 1 rep drop)
            // For 3 reps: 1 tolerance (allow 1 rep drop)
            return when (reps) {
                1 -> 0  // No tolerance - 1→0 is failure
                2, 3 -> 1  // Allow 1 rep drop
                else -> maxOf(1, reps - 1)
            }
        }
        val percentBased = (reps * REP_TOL_PERCENT).toInt()
        return maxOf(REP_TOL_BASE, percentBased)
    }

    /**
     * Calculates expected rep drop when weight increases using 1RM estimation.
     * Predicts how many reps should be achievable at the new weight based on
     * the old weight/reps combination, using the same approach as DoubleProgressionHelper.
     *
     * @param oldWeight The previous weight used
     * @param oldReps The best reps achieved at the old weight
     * @param newWeight The new (higher) weight
     * @param targetRIR Reps in reserve (default 2.0, matching DoubleProgressionHelper)
     * @return Expected number of reps at the new weight
     */
    private fun calculateExpectedRepDrop(
        oldWeight: Double,
        oldReps: Int,
        newWeight: Double,
        targetRIR: Double = 2.0  // Reps in reserve (like DoubleProgressionHelper uses)
    ): Int {
        // Estimate 1RM from old weight/reps
        val estimated1RM = OneRM.estimate1RM(oldWeight, oldReps)
        
        // Predict reps at new weight with target RIR
        val predictedReps = OneRM.repsForTargetRIR(newWeight, estimated1RM, targetRIR)
        
        return predictedReps.toInt().coerceAtLeast(1)
    }

    /**
     * Calculates dynamic rep tolerance for weight increases based on:
     * - Expected rep drop (from 1RM prediction)
     * - Weight increase percentage
     * - Starting rep count
     *
     * This provides more accurate tolerance than fixed values, accounting for
     * the physiological relationship between weight and reps.
     *
     * @param oldWeight The previous weight
     * @param newWeight The new (higher) weight
     * @param oldReps The best reps at the old weight
     * @param expectedNewReps The expected reps at new weight (from 1RM prediction)
     * @return Dynamic tolerance in reps
     */
    private fun calculateRepToleranceForWeightIncrease(
        oldWeight: Double,
        newWeight: Double,
        oldReps: Int,
        expectedNewReps: Int
    ): Int {
        val weightIncreasePct = (newWeight - oldWeight) / oldWeight
        
        // Base tolerance: ±2 reps or ±20% of expected reps, whichever is larger
        val absoluteTolerance = maxOf(2, (expectedNewReps * 0.20).toInt())
        
        // Scale tolerance based on weight increase percentage
        // Larger weight increases allow more variance
        val scaledTolerance = when {
            weightIncreasePct > 0.10 -> absoluteTolerance + 1  // >10% increase: +1 rep tolerance
            weightIncreasePct > 0.05 -> absoluteTolerance      // 5-10%: base tolerance
            else -> maxOf(absoluteTolerance - 1, 1)            // <5%: slightly stricter
        }
        
        // For very low rep counts, be more strict
        if (oldReps <= 3) {
            return scaledTolerance.coerceAtMost(1)
        }
        
        return scaledTolerance
    }

    /**
     * Gets recent baseline stats from a sliding window of sessions.
     * Returns maps of bin -> best reps and bin -> last total reps seen in the window.
     * 
     * @param baselineResetIndex The index where baseline was last reset (e.g., after deload).
     *                           Will not look back before this index.
     * @param useExternalWeight If true, use external weight for bodyweight sets (checks per-set, not per-session).
     * @param cutoffDate Only consider sessions on or after this date (for 30-day limit).
     */
    private fun getRecentBaseline(
        sessions: List<Session>,
        currentIndex: Int,
        windowSize: Int,
        binSize: Double,
        baselineResetIndex: Int,
        useExternalWeight: Boolean = false,
        cutoffDate: LocalDate? = null
    ): Pair<Map<Double, Int>, Map<Double, Int>> {
        val bestRepsAtBin = mutableMapOf<Double, Int>()
        val lastTotalRepsAtBin = mutableMapOf<Double, Int>()
        
        // Look back up to windowSize sessions, but not beyond baselineResetIndex or index 0
        val startIndex = maxOf(baselineResetIndex, currentIndex - windowSize)
        
        for (i in startIndex until currentIndex) {
            val session = sessions[i]
            // Skip deload sessions in baseline calculation
            if (session.isDeload) continue
            // Skip sessions before cutoff date (30-day limit)
            if (cutoffDate != null && session.date.isBefore(cutoffDate)) continue
            
            val perBinStats = mutableMapOf<Double, Pair<Int, Int>>()
            
            for (set in session.sets) {
                // For bodyweight sets, use external weight if available and useExternalWeight is true
                // Check per-set, not per-session, to handle mixed sessions correctly
                val weightToUse = if (useExternalWeight && session.externalWeights.containsKey(set)) {
                    session.externalWeights[set]!!
                } else {
                    set.weight
                }
                
                val b = weightBin(weightToUse, binSize)
                val r = set.reps
                
                val currentStats = perBinStats[b] ?: Pair(0, 0)
                val bestReps = maxOf(currentStats.first, r)
                val totalReps = currentStats.second + r
                
                perBinStats[b] = Pair(bestReps, totalReps)
            }
            
            // Update baseline stats
            for ((b, stats) in perBinStats) {
                val bestR = stats.first
                val totalR = stats.second
                
                if (b !in bestRepsAtBin || bestR > bestRepsAtBin[b]!!) {
                    bestRepsAtBin[b] = bestR
                }
                lastTotalRepsAtBin[b] = totalR
            }
        }
        
        return Pair(bestRepsAtBin, lastTotalRepsAtBin)
    }

    /**
     * Converts SetHistory records to Session objects.
     * Groups by workoutHistoryId, filters for WorkSet only, and sorts by date.
     * Includes deload sessions but marks them with isDeload flag for baseline reset handling.
     */
    fun convertToSessions(
        setHistories: List<SetHistory>,
        workoutHistories: Map<UUID, WorkoutHistory>,
        progressionStatesByWorkoutHistoryId: Map<UUID, ProgressionState> = emptyMap()
    ): List<Session> {

        // Group set histories by workoutHistoryId
        val setsByWorkoutHistoryId = setHistories
            .filter { it.workoutHistoryId != null }
            .groupBy { it.workoutHistoryId!! }

        // Convert to sessions
        var noWorkoutHistoryCount = 0
        var noWorkingSetsCount = 0
        
        val sessions = setsByWorkoutHistoryId.mapNotNull { (workoutHistoryId, setHistories) ->
            val workoutHistory = workoutHistories[workoutHistoryId] ?: run {
                noWorkoutHistoryCount++
                return@mapNotNull null
            }

            // Check if this is a deload session
            val progressionState = progressionStatesByWorkoutHistoryId[workoutHistoryId]
            val isDeload = progressionState == ProgressionState.DELOAD

            // Filter for WorkSet only and extract weight/reps
            val workingSets = mutableListOf<SimpleSet>()
            val externalWeights = mutableMapOf<SimpleSet, Double>()
            var hasBodyweightSets = false
            
            setHistories.forEach { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> {
                        if (setData.subCategory == SetSubCategory.WorkSet) {
                            val simpleSet = SimpleSet(setData.getWeight(), setData.actualReps)
                            workingSets.add(simpleSet)
                        }
                    }
                    is BodyWeightSetData -> {
                        if (setData.subCategory == SetSubCategory.WorkSet) {
                            hasBodyweightSets = true
                            val totalWeight = setData.getWeight()
                            val externalWeight = setData.additionalWeight
                            val simpleSet = SimpleSet(totalWeight, setData.actualReps)
                            workingSets.add(simpleSet)
                            externalWeights[simpleSet] = externalWeight
                        }
                    }
                    else -> {}
                }
            }

            // Only create session if it has working sets
            if (workingSets.isEmpty()) {
                noWorkingSetsCount++
                null
            } else {
                Session(
                    workoutHistoryId, 
                    workoutHistory.date, 
                    workingSets, 
                    isDeload,
                    hasBodyweightSets,
                    externalWeights
                )
            }
        }

        // Sort by date ascending (oldest first)
        val sortedSessions = sessions.sortedBy { it.date }

        return sortedSessions
    }

    /**
     * Main plateau detection function.
     * Uses a sliding window approach to compare against recent baseline instead of all-time bests.
     *
     * Input:
     *   sessions: list of Session sorted by date asc
     *   binSize: BIN_SIZE for weight clustering
     *
     * Output:
     *   plateau: boolean (true = in plateau)
     *   session_improved: array[bool] same length as sessions
     */
    fun detectPlateau(sessions: List<Session>, binSize: Double): Triple<Boolean, List<Boolean>, String> {
        if (sessions.isEmpty()) {
            return Triple(false, emptyList(), "")
        }

        // Filter sessions to only include those within MAX_DAYS_FOR_PLATEAU_DETECTION of the most recent session
        val mostRecentDate = sessions.maxOf { it.date }
        val cutoffDate = mostRecentDate.minusDays(MAX_DAYS_FOR_PLATEAU_DETECTION)
        val filteredSessions = sessions.filter { it.date.isAfter(cutoffDate) || it.date == cutoffDate }
        
        val n = filteredSessions.size

        if (n < MIN_SESS_FOR_PLAT) {
            return Triple(false, List(sessions.size) { false }, "")
        }

        val sessionImproved = MutableList(sessions.size) { false }
        // Map from filtered session index to original session index
        val filteredToOriginalIndex = sessions.mapIndexedNotNull { originalIdx, session ->
            if (session.date.isAfter(cutoffDate) || session.date == cutoffDate) {
                originalIdx
            } else null
        }

        // Track recent baseline that resets after deload sessions, sparse gaps, or program changes
        var baselineResetIndex = 0 // Index where baseline window should start (resets after deload/gap/change)

        // -----------------------------
        // MAIN LOOP OVER SESSIONS
        // -----------------------------
        for (i in 0 until n) {
            val session = filteredSessions[i]
            val originalIndex = filteredToOriginalIndex[i]
            
            // Edge case 1 & 2: Reset baseline if we encounter a deload session or sparse training gap
            if (session.isDeload) {
                baselineResetIndex = i + 1 // Reset baseline window starting from next session
                sessionImproved[originalIndex] = false // Deload sessions don't count as improvement
                continue
            }
            
            // Aggregate per-bin stats for this session
            // Edge case 4: Track all weight bins properly, not just best per bin
            val perBinStats = mutableMapOf<Double, Pair<Int, Int>>() // bin -> (best_reps, total_reps)

            for (set in session.sets) {
                // Edge case 3: For bodyweight exercises, use external weight instead of total weight
                val weightToUse = if (session.isBodyweightExercise && session.externalWeights.containsKey(set)) {
                    session.externalWeights[set]!!
                } else {
                    set.weight
                }
                
                val b = weightBin(weightToUse, binSize)
                val r = set.reps

                val currentStats = perBinStats[b] ?: Pair(0, 0)
                val bestReps = maxOf(currentStats.first, r)
                val totalReps = currentStats.second + r

                perBinStats[b] = Pair(bestReps, totalReps)
            }

            // Edge case 1: Check for sparse/irregular training history
            // If gap between this session and previous session exceeds MAX_DAYS_BETWEEN_SESSIONS, reset baseline
            if (i > 0) {
                val previousSession = filteredSessions[i - 1]
                val daysBetween = ChronoUnit.DAYS.between(previousSession.date, session.date)
                if (daysBetween > MAX_DAYS_BETWEEN_SESSIONS) {
                    baselineResetIndex = i // Reset baseline starting from this session
                }
            }

            // Get recent baseline from sliding window (starting from baselineResetIndex)
            // Edge case 3: Use external weight for bodyweight exercises in baseline comparison
            // Also respect the 30-day limit when looking back
            val useExternalWeightForBaseline = session.isBodyweightExercise
            var (recentBestRepsAtBin, recentLastTotalRepsAtBin) = getRecentBaseline(
                filteredSessions, i, RECENT_BASELINE_WINDOW, binSize, baselineResetIndex, useExternalWeightForBaseline, cutoffDate
            )
            
            // Edge case 2: Detect significant weight drops (program changes)
            // If max weight in current session is significantly below max weight in baseline, reset baseline
            if (recentBestRepsAtBin.isNotEmpty() && perBinStats.isNotEmpty()) {
                val maxWeightInBaseline = recentBestRepsAtBin.keys.maxOrNull()
                val maxWeightInCurrentSession = perBinStats.keys.maxOrNull()
                
                if (maxWeightInBaseline != null && maxWeightInCurrentSession != null) {
                    val weightDrop = (maxWeightInBaseline - maxWeightInCurrentSession) / maxWeightInBaseline
                    if (weightDrop > WEIGHT_DROP_THRESHOLD) {
                        baselineResetIndex = i // Reset baseline starting from this session
                        // Recalculate baseline after reset
                        val (newRecentBestRepsAtBin, newRecentLastTotalRepsAtBin) = getRecentBaseline(
                            filteredSessions, i, RECENT_BASELINE_WINDOW, binSize, baselineResetIndex, useExternalWeightForBaseline, cutoffDate
                        )
                        recentBestRepsAtBin = newRecentBestRepsAtBin
                        recentLastTotalRepsAtBin = newRecentLastTotalRepsAtBin
                    }
                }
            }

            var improved = false

            // If there's no recent baseline (first session or first after deload), mark as improvement
            // This establishes the new baseline
            if (recentBestRepsAtBin.isEmpty()) {
                improved = true
            } else {
                // 1) CONDITION A & C: same-weight improvements (against recent baseline)
                for ((b, stats) in perBinStats) {
                    val bestR = stats.first
                    val totalR = stats.second

                    // Condition A: at same weight bin, best reps increase by ≥1 compared to recent baseline
                    if (b in recentBestRepsAtBin) {
                        val recentBest = recentBestRepsAtBin[b]!!
                        val conditionAMet = bestR >= recentBest + 1
                        if (conditionAMet) {
                            improved = true
                        }
                    } else {
                        // Weight not in baseline - check if it's a new heavier weight (handled by Condition B)
                        // or if it's lighter/same weight but outside baseline window
                        // For now, don't mark as improved here - let Condition B handle it
                    }

                    // Condition C: at same weight bin, total volume increases by ≥ MIN_VOLUME_DELTA
                    if (b in recentLastTotalRepsAtBin) {
                        val recentTotal = recentLastTotalRepsAtBin[b]!!
                        val conditionCMet = totalR >= recentTotal + MIN_VOLUME_DELTA
                        if (conditionCMet) {
                            improved = true
                        }
                    }
                }

                // 2) CONDITION B: weight increase with acceptable rep drop
                //    Compare to recent baseline, and handle weight increases to previously-seen weights
                //    Edge case 4: Check ALL new weight bins, not just max weight (handles step loading)
                //    Only check this if Condition A and C didn't already mark as improved
                if (!improved) {
                    val maxWeightInBaseline = recentBestRepsAtBin.keys.maxOrNull() ?: Double.NEGATIVE_INFINITY
                    
                    // Edge case 4: Check all weight bins in current session, not just max
                    // This allows step loading within a session (e.g., back-off sets) to count as progress
                    for ((b, stats) in perBinStats) {
                        val currentBin = b
                        val currentReps = stats.first

                        // Condition B applies to NEW weights (heavier than baseline max or not in baseline)
                        // Skip if this weight was already handled by Condition A
                        if (currentBin > maxWeightInBaseline && currentBin !in recentBestRepsAtBin) {
                            // New weight: compare to best reps at lower weights in recent baseline
                            var bestRepsLower = Int.MIN_VALUE
                            for ((bHist, repsHist) in recentBestRepsAtBin) {
                                if (bHist < currentBin && repsHist > bestRepsLower) {
                                    bestRepsLower = repsHist
                                }
                            }
                            
                            if (bestRepsLower != Int.MIN_VALUE) {
                                // Find the weight that corresponds to bestRepsLower
                                var bestLowerWeight = Double.NEGATIVE_INFINITY
                                for ((bHist, repsHist) in recentBestRepsAtBin) {
                                    if (bHist < currentBin && repsHist == bestRepsLower) {
                                        bestLowerWeight = bHist
                                        break
                                    }
                                }
                                
                                // Calculate expected rep drop using 1RM
                                val expectedNewReps = calculateExpectedRepDrop(
                                    oldWeight = bestLowerWeight,  // Use the best lower weight from baseline
                                    oldReps = bestRepsLower,
                                    newWeight = currentBin
                                )
                                
                                // Calculate dynamic tolerance
                                val dynamicTolerance = calculateRepToleranceForWeightIncrease(
                                    oldWeight = bestLowerWeight,
                                    newWeight = currentBin,
                                    oldReps = bestRepsLower,
                                    expectedNewReps = expectedNewReps
                                )
                                
                                // Check if actual reps are within tolerance of expected
                                val minAcceptableReps = maxOf(1, expectedNewReps - dynamicTolerance)
                                val conditionBMet = currentReps >= minAcceptableReps
                                
                                // Also check for extreme cases: if rep drop is >50% of old reps, be more strict
                                val repDropPct = (bestRepsLower - currentReps).toDouble() / bestRepsLower
                                val isExtremeDrop = repDropPct > 0.50 && currentReps < 3
                                
                                if (conditionBMet && !isExtremeDrop) {
                                    improved = true
                                    break // Any qualifying new weight bin counts as improvement
                                }
                                // If conditionBMet is false or isExtremeDrop is true, don't mark as improved
                            } else {
                                // No lower weight in baseline, but this is new max = improvement
                                improved = true
                                break
                            }
                        }
                        // Note: We don't check else if currentBin in recentBestRepsAtBin here
                        // because Condition A should have already handled same-weight cases
                    }
                }
            }

            // Mark this session (use original index)
            sessionImproved[originalIndex] = improved
        }

        // -----------------------------
        // PLATEAU DECISION
        // -----------------------------

        // Edge case 8: Look at the last WINDOW_SESS non-deload sessions
        // Count backwards from the end, skipping deload sessions
        val nonDeloadSessionsInWindow = mutableListOf<Int>()
        var count = 0
        var idx = n - 1
        while (idx >= 0 && count < WINDOW_SESS) {
            if (!filteredSessions[idx].isDeload) {
                nonDeloadSessionsInWindow.add(idx)
                count++
            }
            idx--
        }

        // Require enough total sessions before calling plateau (not just window size)
        if (n < MIN_SESS_FOR_PLAT) {
            return Triple(false, sessionImproved, "")
        }

        // Edge case 8: If we don't have enough non-deload sessions in the window,
        // require minimum number of non-deload sessions before checking for plateau
        if (nonDeloadSessionsInWindow.size < WINDOW_SESS) {
            // Not enough non-deload sessions to determine plateau
            return Triple(false, sessionImproved, "")
        }

        var recentHasImprovement = false
        for (i in nonDeloadSessionsInWindow) {
            val originalIndex = filteredToOriginalIndex[i]
            if (sessionImproved[originalIndex]) {
                recentHasImprovement = true
                break
            }
        }

        val plateau = !recentHasImprovement

        // Build reason message if plateau detected
        val reason = if (plateau) {
            buildPlateauReasonMessage(filteredSessions, nonDeloadSessionsInWindow, binSize)
        } else {
            ""
        }

        return Triple(plateau, sessionImproved, reason)
    }

    /**
     * Builds a detailed reason message explaining why a plateau was detected.
     */
    private fun buildPlateauReasonMessage(
        filteredSessions: List<Session>,
        nonDeloadSessionsInWindow: List<Int>,
        binSize: Double
    ): String {
        val sessionDetails = mutableListOf<String>()
        var sessionNumber = 1
        
        // Get sessions in reverse order (most recent first) for display
        val sessionsToShow = nonDeloadSessionsInWindow.reversed()
        
        for (sessionIdx in sessionsToShow) {
            val session = filteredSessions[sessionIdx]
            
            // Find best weight/reps combination for this session
            var bestWeight = 0.0
            var bestReps = 0
            
            for (set in session.sets) {
                // For bodyweight exercises, use external weight if available
                val weightToUse = if (session.isBodyweightExercise && session.externalWeights.containsKey(set)) {
                    session.externalWeights[set]!!
                } else {
                    set.weight
                }
                
                // Track best weight/reps (prioritize higher weight, then higher reps)
                if (weightToUse > bestWeight || (weightToUse == bestWeight && set.reps > bestReps)) {
                    bestWeight = weightToUse
                    bestReps = set.reps
                }
            }
            
            // Format weight
            val weightStr = if (bestWeight == 0.0) {
                "BW"
            } else if (bestWeight % 1.0 == 0.0) {
                "${bestWeight.toInt()}kg"
            } else {
                String.format("%.2f", bestWeight).trimEnd('0').trimEnd('.') + "kg"
            }
            
            sessionDetails.add("• Session $sessionNumber: $weightStr × $bestReps reps")
            sessionNumber++
        }
        
        return buildString {
            append("No improvement detected in the last ${WINDOW_SESS} sessions.\n\n")
            append("Recent sessions:\n")
            sessionDetails.forEach { append("$it\n") }
            append("\nTo break the plateau, try increasing weight, reps, or total volume.")
        }
    }

    /**
     * Convenience function that converts SetHistory records to Session objects
     * and calls detectPlateau.
     * Excludes sessions that are marked as DELOAD in the progressionStates map.
     * 
     * @param equipment Equipment used for the exercise. Used to calculate BIN_SIZE.
     *                  If null, uses DEFAULT_BIN_SIZE (0.25 kg).
     */
    fun detectPlateauFromHistories(
        setHistories: List<SetHistory>,
        workoutHistories: Map<UUID, WorkoutHistory>,
        progressionStatesByWorkoutHistoryId: Map<UUID, ProgressionState> = emptyMap(),
        equipment: WeightLoadedEquipment? = null
    ): Triple<Boolean, List<Boolean>, String> {
        val sessions = convertToSessions(setHistories, workoutHistories, progressionStatesByWorkoutHistoryId)
        val binSize = calculateBinSize(equipment)
        val result = detectPlateau(sessions, binSize)
        
        return result
    }
}

