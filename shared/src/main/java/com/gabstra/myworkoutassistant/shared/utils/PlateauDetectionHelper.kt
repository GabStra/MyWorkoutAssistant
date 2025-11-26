package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import java.time.LocalDate
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
    private const val MIN_SESS_FOR_PLAT = 3       // minimal sessions before calling plateau
    private const val RECENT_BASELINE_WINDOW = 10 // how many recent sessions to use for baseline comparison
    
    // Cache for BIN_SIZE per equipment
    private val binSizeCache: MutableMap<UUID, Double> = mutableMapOf()

    // -----------------------------
    // DATA CLASSES
    // -----------------------------
    data class Session(
        val id: UUID,              // workoutHistoryId
        val date: LocalDate,
        val sets: List<SimpleSet>, // weight and reps for working sets only
        val isDeload: Boolean = false // true if this session was marked as DELOAD
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
            for (i in 0 until weights.size - 1) {
                val diff = weights[i + 1] - weights[i]
                if (diff > 1e-9) { // Only consider positive differences
                    differences.add(diff)
                }
            }

            // If no valid differences, use default
            if (differences.isEmpty()) {
                val binSize = DEFAULT_BIN_SIZE
                binSizeCache[equipment.id] = binSize
                return binSize
            }
            
            // Calculate GCD of all differences
            val binSize = gcdOfList(differences)

            // Ensure BIN_SIZE is positive and reasonable
            val finalBinSize = if (binSize > 1e-9) binSize else DEFAULT_BIN_SIZE

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
     */
    private fun calculateRepTolerance(reps: Int): Int {
        val percentBased = (reps * REP_TOL_PERCENT).toInt()
        return maxOf(REP_TOL_BASE, percentBased)
    }

    /**
     * Gets recent baseline stats from a sliding window of sessions.
     * Returns maps of bin -> best reps and bin -> last total reps seen in the window.
     * 
     * @param baselineResetIndex The index where baseline was last reset (e.g., after deload).
     *                           Will not look back before this index.
     */
    private fun getRecentBaseline(
        sessions: List<Session>,
        currentIndex: Int,
        windowSize: Int,
        binSize: Double,
        baselineResetIndex: Int
    ): Pair<Map<Double, Int>, Map<Double, Int>> {
        val bestRepsAtBin = mutableMapOf<Double, Int>()
        val lastTotalRepsAtBin = mutableMapOf<Double, Int>()
        
        // Look back up to windowSize sessions, but not beyond baselineResetIndex or index 0
        val startIndex = maxOf(baselineResetIndex, currentIndex - windowSize)
        
        for (i in startIndex until currentIndex) {
            val session = sessions[i]
            // Skip deload sessions in baseline calculation
            if (session.isDeload) continue
            
            val perBinStats = mutableMapOf<Double, Pair<Int, Int>>()
            
            for (set in session.sets) {
                val b = weightBin(set.weight, binSize)
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
            val workingSets = setHistories
                .filter { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> setData.subCategory == SetSubCategory.WorkSet
                        is BodyWeightSetData -> setData.subCategory == SetSubCategory.WorkSet
                        else -> false
                    }
                }
                .mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                        is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                        else -> null
                    }
                }
            

            // Only create session if it has working sets
            if (workingSets.isEmpty()) {
                noWorkingSetsCount++
                null
            } else {
                Session(workoutHistoryId, workoutHistory.date, workingSets, isDeload)
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
    fun detectPlateau(sessions: List<Session>, binSize: Double): Pair<Boolean, List<Boolean>> {
        val n = sessions.size

        if (n < MIN_SESS_FOR_PLAT) {
            return false to List(n) { false }
        }

        val sessionImproved = MutableList(n) { false }

        // Track recent baseline that resets after deload sessions
        var baselineResetIndex = 0 // Index where baseline window should start (resets after deload)

        // -----------------------------
        // MAIN LOOP OVER SESSIONS
        // -----------------------------
        for (i in 0 until n) {
            val session = sessions[i]
            
            // Reset baseline if we encounter a deload session
            if (session.isDeload) {
                baselineResetIndex = i + 1 // Reset baseline window starting from next session
                sessionImproved[i] = false // Deload sessions don't count as improvement
                continue
            }
            
            // Aggregate per-bin stats for this session
            val perBinStats = mutableMapOf<Double, Pair<Int, Int>>() // bin -> (best_reps, total_reps)

            for (set in session.sets) {
                val b = weightBin(set.weight, binSize)
                val r = set.reps

                val currentStats = perBinStats[b] ?: Pair(0, 0)
                val bestReps = maxOf(currentStats.first, r)
                val totalReps = currentStats.second + r

                perBinStats[b] = Pair(bestReps, totalReps)
            }

            // Get recent baseline from sliding window (starting from baselineResetIndex)
            val (recentBestRepsAtBin, recentLastTotalRepsAtBin) = getRecentBaseline(
                sessions, i, RECENT_BASELINE_WINDOW, binSize, baselineResetIndex
            )

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
                        // First time seeing this weight in recent baseline window = improvement
                        improved = true
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
                if (!improved) {
                    val maxWeightInBaseline = recentBestRepsAtBin.keys.maxOrNull() ?: Double.NEGATIVE_INFINITY
                    
                    for ((b, stats) in perBinStats) {
                        val currentBin = b
                        val currentReps = stats.first

                        // Check if this weight is higher than any weight in recent baseline
                        if (currentBin > maxWeightInBaseline) {
                            // New heaviest weight: compare to best reps at lower weights in recent baseline
                            var bestRepsLower = Int.MIN_VALUE
                            for ((bHist, repsHist) in recentBestRepsAtBin) {
                                if (bHist < currentBin && repsHist > bestRepsLower) {
                                    bestRepsLower = repsHist
                                }
                            }
                            
                            if (bestRepsLower != Int.MIN_VALUE) {
                                val repTolerance = calculateRepTolerance(bestRepsLower)
                                val conditionBMet = currentReps >= bestRepsLower - repTolerance
                                if (conditionBMet) {
                                    improved = true
                                    break
                                }
                            } else {
                                // No lower weight in baseline, but this is new max = improvement
                                improved = true
                                break
                            }
                        } else if (currentBin in recentBestRepsAtBin) {
                            // Weight was seen in recent baseline
                            // Check if current reps are higher than recent baseline for this weight
                            // (This supplements Condition A for cases where we're revisiting a weight)
                            val recentRepsAtBin = recentBestRepsAtBin[currentBin]!!
                            if (currentReps > recentRepsAtBin) {
                                improved = true
                                break
                            }
                        }
                    }
                }
            }

            // Mark this session
            sessionImproved[i] = improved
        }

        // -----------------------------
        // PLATEAU DECISION
        // -----------------------------

        // Look at the last WINDOW_SESS sessions (excluding deload sessions)
        val start = maxOf(0, n - WINDOW_SESS)
        val end = n - 1

        // Require enough sessions before calling plateau
        if ((end - start + 1) < MIN_SESS_FOR_PLAT) {
            return Pair(false, sessionImproved)
        }

        var recentHasImprovement = false
        for (i in start..end) {
            if (sessionImproved[i]) {
                recentHasImprovement = true
                break
            }
        }

        val plateau = !recentHasImprovement

        return Pair(plateau, sessionImproved)
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
    ): Pair<Boolean, List<Boolean>> {
        val sessions = convertToSessions(setHistories, workoutHistories, progressionStatesByWorkoutHistoryId)
        val binSize = calculateBinSize(equipment)
        val result = detectPlateau(sessions, binSize)
        
        return result
    }
}

