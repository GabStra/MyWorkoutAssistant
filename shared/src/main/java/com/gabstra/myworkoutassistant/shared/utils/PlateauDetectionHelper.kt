package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import java.time.LocalDate
import java.util.UUID

object PlateauDetectionHelper {
    // -----------------------------
    // CONFIG (TUNE THESE)
    // -----------------------------
    private const val BIN_SIZE = 0.5      // kg; for weight clustering (e.g., 62.5, 63.0, 63.5)
    private const val REP_TOL = 2          // allowed rep drop when increasing weight
    private const val MIN_VOLUME_DELTA = 2 // extra total reps to count as progress
    private const val WINDOW_SESS = 5      // how many recent sessions to inspect
    private const val MIN_SESS_FOR_PLAT = 4 // minimal sessions before calling plateau

    // -----------------------------
    // DATA CLASSES
    // -----------------------------
    data class Session(
        val id: UUID,              // workoutHistoryId
        val date: LocalDate,
        val sets: List<SimpleSet>  // weight and reps for working sets only
    )

    // -----------------------------
    // HELPERS
    // -----------------------------
    private fun weightBin(weight: Double): Double {
        return kotlin.math.round(weight / BIN_SIZE) * BIN_SIZE
    }

    /**
     * Converts SetHistory records to Session objects.
     * Groups by workoutHistoryId, filters for WorkSet only, and sorts by date.
     */
    fun convertToSessions(
        setHistories: List<SetHistory>,
        workoutHistories: Map<UUID, WorkoutHistory>
    ): List<Session> {
        // Group set histories by workoutHistoryId
        val setsByWorkoutHistoryId = setHistories
            .filter { it.workoutHistoryId != null }
            .groupBy { it.workoutHistoryId!! }

        // Convert to sessions
        val sessions = setsByWorkoutHistoryId.mapNotNull { (workoutHistoryId, setHistories) ->
            val workoutHistory = workoutHistories[workoutHistoryId] ?: return@mapNotNull null

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
            if (workingSets.isEmpty()) null
            else Session(workoutHistoryId, workoutHistory.date, workingSets)
        }

        // Sort by date ascending (oldest first)
        return sessions.sortedBy { it.date }
    }

    /**
     * Main plateau detection function.
     *
     * Input:
     *   sessions: list of Session sorted by date asc
     *
     * Output:
     *   plateau: boolean (true = in plateau)
     *   session_improved: array[bool] same length as sessions
     */
    fun detectPlateau(sessions: List<Session>): Pair<Boolean, List<Boolean>> {
        val n = sessions.size

        if (n < MIN_SESS_FOR_PLAT) {
            return Pair(false, emptyList()) // not enough data yet
        }

        // Per-bin historical info
        val bestRepsAtBin = mutableMapOf<Double, Int>()        // bin -> best single-set reps ever at this bin
        val lastTotalRepsAtBin = mutableMapOf<Double, Int>()    // bin -> total reps last time this bin was used

        val sessionImproved = MutableList(n) { false }

        // -----------------------------
        // MAIN LOOP OVER SESSIONS
        // -----------------------------
        for (i in 0 until n) {
            val session = sessions[i]

            // Aggregate per-bin stats for this session
            // per_bin_stats: bin -> { best_reps, total_reps }
            val perBinStats = mutableMapOf<Double, Pair<Int, Int>>() // bin -> (best_reps, total_reps)

            for (set in session.sets) {
                val b = weightBin(set.weight)
                val r = set.reps

                val currentStats = perBinStats[b] ?: Pair(0, 0)
                val bestReps = maxOf(currentStats.first, r)
                val totalReps = currentStats.second + r

                perBinStats[b] = Pair(bestReps, totalReps)
            }

            var improved = false

            // 1) CONDITION A & C: same-weight improvements
            for ((b, stats) in perBinStats) {
                val bestR = stats.first
                val totalR = stats.second

                // Condition A: at same weight bin, best reps increase by ≥1
                if (b in bestRepsAtBin) {
                    if (bestR >= bestRepsAtBin[b]!! + 1) {
                        improved = true
                    }
                }

                // Condition C: at same weight bin, total volume increases by ≥ MIN_VOLUME_DELTA
                if (b in lastTotalRepsAtBin) {
                    if (totalR >= lastTotalRepsAtBin[b]!! + MIN_VOLUME_DELTA) {
                        improved = true
                    }
                }
            }

            // 2) CONDITION B: higher weight with acceptable rep drop
            //    For each bin used in this session, compare to lower-weight history
            //    (only matters if we have previous bins below it)
            if (!improved) {
                for ((b, stats) in perBinStats) {
                    val higherBin = b
                    val higherReps = stats.first

                    // find best reps among all lower bins we've seen in the past
                    var bestRepsLower = Int.MIN_VALUE
                    for ((bHist, repsHist) in bestRepsAtBin) {
                        if (bHist < higherBin) {
                            if (repsHist > bestRepsLower) {
                                bestRepsLower = repsHist
                            }
                        }
                    }

                    if (bestRepsLower == Int.MIN_VALUE) {
                        continue // no lower weight history to compare against
                    }

                    // Condition B:
                    // weight increased (implicitly, because higher_bin > any lower b_hist)
                    // and reps did NOT fall more than REP_TOL below best at lower weights
                    if (higherReps >= bestRepsLower - REP_TOL) {
                        improved = true
                        break
                    }
                }
            }

            // 3) Mark this session
            sessionImproved[i] = improved

            // 4) Update historical per-bin info AFTER checking improvement
            for ((b, stats) in perBinStats) {
                val bestR = stats.first
                val totalR = stats.second

                if (b !in bestRepsAtBin || bestR > bestRepsAtBin[b]!!) {
                    bestRepsAtBin[b] = bestR
                }

                lastTotalRepsAtBin[b] = totalR
            }
        }

        // -----------------------------
        // PLATEAU DECISION
        // -----------------------------

        // Look at the last WINDOW_SESS sessions
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
     */
    fun detectPlateauFromHistories(
        setHistories: List<SetHistory>,
        workoutHistories: Map<UUID, WorkoutHistory>
    ): Pair<Boolean, List<Boolean>> {
        val sessions = convertToSessions(setHistories, workoutHistories)
        return detectPlateau(sessions)
    }
}

