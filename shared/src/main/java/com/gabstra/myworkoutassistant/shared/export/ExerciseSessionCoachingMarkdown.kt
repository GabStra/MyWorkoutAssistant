package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToInt

internal data class ComparableExerciseSession(
    val workoutHistory: WorkoutHistory,
    val workout: Workout?,
    val activeSetHistories: List<SetHistory>,
    val progression: ExerciseSessionProgression?,
)

private data class ExportSessionMetrics(
    val executedSetCount: Int,
    val simpleSets: List<SimpleSet>,
    val setSummaryEntries: List<String>,
    val totalVolume: Double,
    val totalDurationSeconds: Int,
)

internal suspend fun loadComparableExerciseSessions(
    exercise: Exercise,
    workouts: List<Workout>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
): List<ComparableExerciseSession> {
    val workoutsContainingExercise = workouts.filter { workout ->
        workout.workoutComponents.any { component ->
            when (component) {
                is Exercise -> component.id == exercise.id
                is Superset -> component.exercises.any { it.id == exercise.id }
                else -> false
            }
        }
    }
    if (workoutsContainingExercise.isEmpty()) return emptyList()

    val workoutsById = workoutsContainingExercise.associateBy { it.id }
    val completedWorkoutHistories = workoutsContainingExercise
        .flatMap { workout -> workoutHistoryDao.getWorkoutsByWorkoutId(workout.id) }
        .filter { it.isDone }
        .sortedWith(compareBy<WorkoutHistory> { it.date }.thenBy { it.time })

    return completedWorkoutHistories.mapNotNull { workoutHistory ->
        val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
            workoutHistory.id,
            exercise.id
        ).sortedBy { it.order }
        val activeSetHistories = setHistories.filterForInsightComparisonSets()
        if (activeSetHistories.isEmpty()) {
            null
        } else {
            ComparableExerciseSession(
                workoutHistory = workoutHistory,
                workout = workoutsById[workoutHistory.workoutId],
                activeSetHistories = activeSetHistories,
                progression = exerciseSessionProgressionDao.getByWorkoutHistoryIdAndExerciseId(
                    workoutHistory.id,
                    exercise.id
                )
            )
        }
    }
}

internal fun List<SetHistory>.filterForInsightComparisonSets(): List<SetHistory> {
    return filterNot { setHistory ->
        when (val setData = setHistory.setData) {
            is RestSetData -> true
            is WeightSetData -> setData.subCategory.isExcludedFromInsightComparison()
            is BodyWeightSetData -> setData.subCategory.isExcludedFromInsightComparison()
            else -> false
        }
    }
}

private fun SetSubCategory.isExcludedFromInsightComparison(): Boolean {
    return this == SetSubCategory.WarmupSet ||
        this == SetSubCategory.CalibrationPendingSet ||
        this == SetSubCategory.CalibrationSet
}

internal fun appendExerciseContextMarkdown(
    markdown: StringBuilder,
    exercise: Exercise,
    workoutStore: WorkoutStore,
    equipmentName: String?,
) {
    markdown.append("#### Context\n")
    markdown.append("- Type: ${exercise.exerciseType.name}\n")
    equipmentName?.let { markdown.append("- Equipment: $it\n") }

    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT && exercise.bodyWeightPercentage != null) {
        markdown.append("- Body weight percentage: ${formatNumber(exercise.bodyWeightPercentage)}%\n")
    }

    if (exercise.exerciseType != ExerciseType.COUNTDOWN && exercise.exerciseType != ExerciseType.COUNTUP) {
        markdown.append("- Rep range: ${exercise.minReps}-${exercise.maxReps}\n")
    }

    if (exercise.exerciseType == ExerciseType.WEIGHT) {
        markdown.append(
            "- Load range: ${formatNumber(exercise.minLoadPercent)}%-${formatNumber(exercise.maxLoadPercent)}%\n"
        )
    }

    markdown.append("- Progression mode: ${exercise.progressionMode.name}\n")

    if (exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null) {
        markdown.append(
            "- Exercise target zone: ${formatPercentValue(exercise.lowerBoundMaxHRPercent.toDouble())}%-${formatPercentValue(exercise.upperBoundMaxHRPercent.toDouble())}% of max HR\n"
        )
    }

    if (exercise.intraSetRestInSeconds != null && exercise.intraSetRestInSeconds > 0) {
        markdown.append("- Intra-set rest: ${exercise.intraSetRestInSeconds}s\n")
    }

    markdown.append("- Warm-up sets: ${if (exercise.generateWarmUpSets) "enabled" else "disabled"}\n")

    if (exercise.notes.isNotBlank()) {
        markdown.append("- Notes: ${exercise.notes}\n")
    }

    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        markdown.append("- Current profile body weight: ${formatNumber(workoutStore.weightKg)} kg\n")
    }

    markdown.append("\n")
}

private fun formatPercentValue(value: Double): String {
    val normalized = if (value in 0.0..1.0) value * 100.0 else value
    return formatNumber(normalized)
}

internal fun appendPlannedMarkdown(
    markdown: StringBuilder,
    exercise: Exercise,
) {
    markdown.append("#### Planned\n")
    if (exercise.sets.isEmpty()) {
        markdown.append("- None\n\n")
        return
    }

    exercise.sets.forEachIndexed { index, set ->
        markdown.append("- P${index + 1}: ${formatSetInlineForExport(set)}\n")
    }
    markdown.append("\n")
}

internal fun appendHistoricalSessionBlockMarkdown(
    markdown: StringBuilder,
    heading: String,
    session: ComparableExerciseSession?,
    achievableWeights: List<Double>?,
    includeSelectionNote: Boolean = false,
) {
    markdown.append("#### $heading\n")
    if (session == null) {
        markdown.append("- None\n\n")
        return
    }

    val metrics = metricsForSetHistories(session.activeSetHistories, achievableWeights)
    markdown.append("- Date: ${session.workoutHistory.date} ${session.workoutHistory.time}\n")
    session.workout?.name?.let { markdown.append("- Workout: $it\n") }
    markdown.append("- Executed sets: ${metrics.executedSetCount}\n")
    if (metrics.totalVolume > 0.0) {
        markdown.append("- Total volume: ${formatNumber(metrics.totalVolume)} kg\n")
    }
    if (metrics.totalDurationSeconds > 0) {
        markdown.append("- Total duration: ${formatDurationForExport(metrics.totalDurationSeconds)}\n")
    }
    session.progression?.let { progression ->
        markdown.append("- Progression state: ${progression.progressionState.name}\n")
    }
    if (includeSelectionNote) {
        markdown.append("- Note: selected session\n")
    }
    session.activeSetHistories.forEachIndexed { index, setHistory ->
        markdown.append("- S${index + 1}: ${formatSetHistoryInline(setHistory, achievableWeights)}\n")
    }
    markdown.append("\n")
}

internal fun appendExecutedSummaryMarkdown(
    markdown: StringBuilder,
    session: ComparableExerciseSession,
    achievableWeights: List<Double>?,
) {
    val metrics = metricsForSetHistories(session.activeSetHistories, achievableWeights)
    markdown.append("#### Executed\n")
    markdown.append("- Date: ${session.workoutHistory.date} ${session.workoutHistory.time}\n")
    markdown.append("- Executed sets: ${metrics.executedSetCount}\n")
    if (metrics.totalVolume > 0.0) {
        markdown.append("- Total volume: ${formatNumber(metrics.totalVolume)} kg\n")
    }
    if (metrics.totalDurationSeconds > 0) {
        markdown.append("- Total duration: ${formatDurationForExport(metrics.totalDurationSeconds)}\n")
    }
    if (metrics.setSummaryEntries.isNotEmpty()) {
        markdown.append(
            "- Set summary: ${metrics.setSummaryEntries.joinToString(", ")}\n"
        )
    }
    markdown.append("\n")
}

internal fun appendExerciseTrendMarkdown(
    markdown: StringBuilder,
    sessionsThroughSelected: List<ComparableExerciseSession>,
    selectedSessionId: UUID,
    achievableWeights: List<Double>?,
) {
    val window = sessionsThroughSelected.takeLast(8)
    markdown.append("#### Trend (last ${window.size} sessions)\n")
    window.forEach { session ->
        val metrics = metricsForSetHistories(session.activeSetHistories, achievableWeights)
        val line = buildString {
            append("- ${session.workoutHistory.date}")
            append(" | ")
            append(session.workout?.name ?: "Unknown Workout")
            append(" | Sets: ${metrics.executedSetCount}")
            if (metrics.setSummaryEntries.isNotEmpty()) {
                append(" | ")
                append(metrics.setSummaryEntries.joinToString(", "))
            }
            if (metrics.totalVolume > 0.0) {
                append(" | Vol: ${formatNumber(metrics.totalVolume)}kg")
            }
            if (metrics.totalDurationSeconds > 0) {
                append(" | Dur: ${formatDurationForExport(metrics.totalDurationSeconds)}")
            }
            session.progression?.let {
                append(" | State: ${it.progressionState.name}")
            }
            if (session.workoutHistory.id == selectedSessionId) {
                append(" | selected")
            }
        }
        markdown.append(line).append("\n")
    }
    markdown.append("\n")
}

internal fun appendExerciseRecoveryContextMarkdown(
    markdown: StringBuilder,
    workoutHistory: WorkoutHistory,
    activeSetHistories: List<SetHistory>,
    restsForExercise: List<RestHistory>,
    exercise: Exercise,
    userAge: Int,
    workoutStore: WorkoutStore,
) {
    val workSamples = activeSetHistories.flatMap { history ->
        sliceHeartRateRecords(
            workoutHistory.startTime,
            workoutHistory.heartBeatRecords,
            history.startTime,
            history.endTime
        )
    }.filter { it > 0 }
    val restSamples = restsForExercise.flatMap { history ->
        sliceHeartRateRecords(
            workoutHistory.startTime,
            workoutHistory.heartBeatRecords,
            history.startTime,
            history.endTime
        )
    }.filter { it > 0 }

    if (workSamples.isEmpty() && restSamples.isEmpty()) {
        return
    }

    markdown.append("#### Recovery Context\n")
    if (workSamples.isNotEmpty()) {
        markdown.append(
            "- Work HR: avg ${workSamples.average().roundToInt()} bpm | peak ${workSamples.maxOrNull() ?: 0} bpm\n"
        )
        if (exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null) {
            val lowHr = getHeartRateFromPercentage(
                exercise.lowerBoundMaxHRPercent,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val highHr = getHeartRateFromPercentage(
                exercise.upperBoundMaxHRPercent,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val inZone = workSamples.count { it in lowHr..highHr }
            val pct = (inZone.toDouble() / workSamples.size.toDouble() * 100.0).roundToInt()
            markdown.append("- Work samples in target zone: $pct%\n")
        }
    }
    if (restSamples.isNotEmpty()) {
        markdown.append(
            "- Rest HR: avg ${restSamples.average().roundToInt()} bpm | peak ${restSamples.maxOrNull() ?: 0} bpm\n"
        )
    }
    markdown.append("\n")
}

internal fun appendExerciseCoachingSignalsMarkdown(
    markdown: StringBuilder,
    selectedSession: ComparableExerciseSession,
    previousSession: ComparableExerciseSession?,
    bestSession: ComparableExerciseSession?,
    sessionsThroughSelected: List<ComparableExerciseSession>,
    achievableWeights: List<Double>?,
) {
    val signals = linkedSetOf<String>()
    selectedSession.progression?.let { progression ->
        signals += "progression_state:${progression.progressionState.name.lowercase()}"
        signals += ternarySignal("vs_expected", progression.vsExpected)
        signals += ternarySignal("vs_previous_successful_baseline", progression.vsPrevious)
    }

    previousSession?.let {
        signals += compareSignal(
            prefix = "vs_previous_session",
            selected = selectedSession,
            baseline = it,
            achievableWeights = achievableWeights
        )
    }

    bestSession?.let {
        if (it.workoutHistory.id == selectedSession.workoutHistory.id) {
            signals += "best_to_date"
        } else {
            signals += "below_best_to_date"
        }
    }

    trendSignal(sessionsThroughSelected, achievableWeights)?.let { signals += it }

    markdown.append("#### Coaching Signals\n")
    if (signals.isEmpty()) {
        markdown.append("- None\n\n")
        return
    }

    signals.forEach { signal ->
        markdown.append("- $signal\n")
    }
    markdown.append("\n")
}

internal fun findBestSessionThroughIndex(
    sessions: List<ComparableExerciseSession>,
    selectedIndex: Int,
    achievableWeights: List<Double>?,
): ComparableExerciseSession? {
    val available = sessions.take(selectedIndex + 1)
    if (available.isEmpty()) return null

    var best = available.first()
    for (candidate in available.drop(1)) {
        if (compareSessions(candidate, best, achievableWeights) >= 0) {
            best = candidate
        }
    }
    return best
}

private fun metricsForSetHistories(
    setHistories: List<SetHistory>,
    achievableWeights: List<Double>?,
): ExportSessionMetrics {
    var totalVolume = 0.0
    var totalDurationSeconds = 0
    val simpleSets = mutableListOf<SimpleSet>()
    val setSummaryEntries = mutableListOf<String>()
    var executedSetCount = 0

    for (setHistory in setHistories) {
        if (setHistory.skipped) continue
        executedSetCount += 1
        when (val setData = setHistory.setData) {
            is WeightSetData -> {
                val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
                simpleSets += SimpleSet(adjustedWeight, setData.actualReps)
                setSummaryEntries += formatSimpleSetSummaryEntry(adjustedWeight, setData.actualReps)
                totalVolume += adjustedWeight * setData.actualReps
            }
            is BodyWeightSetData -> {
                val effectiveWeight = setData.getWeight()
                simpleSets += SimpleSet(effectiveWeight, setData.actualReps)
                setSummaryEntries += formatSimpleSetSummaryEntry(effectiveWeight, setData.actualReps)
                totalVolume += setData.volume
            }
            is TimedDurationSetData -> {
                extractActualDurationSeconds(setData)?.let { durationSeconds ->
                    totalDurationSeconds += durationSeconds
                    setSummaryEntries += formatDurationSummaryEntry(durationSeconds)
                }
            }
            is EnduranceSetData -> {
                extractActualDurationSeconds(setData)?.let { durationSeconds ->
                    totalDurationSeconds += durationSeconds
                    setSummaryEntries += formatDurationSummaryEntry(durationSeconds)
                }
            }
            else -> {
                executedSetCount -= 1
            }
        }
    }

    return ExportSessionMetrics(
        executedSetCount = executedSetCount,
        simpleSets = simpleSets,
        setSummaryEntries = setSummaryEntries,
        totalVolume = totalVolume,
        totalDurationSeconds = totalDurationSeconds
    )
}

private fun formatSetHistoryInline(
    setHistory: SetHistory,
    achievableWeights: List<Double>?,
): String {
    val prefix = if (setHistory.skipped) "[skipped] " else ""
    return prefix + when (val setData = setHistory.setData) {
        is WeightSetData -> {
            val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
            "${formatNumber(adjustedWeight)}kg×${setData.actualReps}"
        }
        is BodyWeightSetData -> {
            "${formatNumber(setData.getWeight())}kg×${setData.actualReps}"
        }
        is TimedDurationSetData -> {
            extractActualDurationSeconds(setData)
                ?.let(::formatDurationSummaryEntry)
                ?: "Duration: unknown"
        }
        is EnduranceSetData -> {
            extractActualDurationSeconds(setData)
                ?.let(::formatDurationSummaryEntry)
                ?: "Duration: unknown"
        }
        else -> "Other"
    }
}

private fun formatSimpleSetSummaryEntry(
    weight: Double,
    reps: Int,
): String = "${formatNumber(weight)}kg×$reps"

private fun formatDurationSummaryEntry(
    durationSeconds: Int,
): String = "Duration: ${formatDurationForExport(durationSeconds)}"

private fun extractActualDurationSeconds(
    setData: SetData,
): Int? = when (setData) {
    is TimedDurationSetData -> extractTimedDurationSeconds(setData)
    is EnduranceSetData -> extractEnduranceDurationSeconds(setData)
    else -> null
}

private fun extractTimedDurationSeconds(
    setData: TimedDurationSetData,
): Int {
    val startSeconds = normalizeTimerValueToSeconds(setData.startTimer)
    val endSeconds = normalizeTimerValueToSeconds(setData.endTimer)

    return when {
        startSeconds <= 0 -> 0
        endSeconds in 1 until startSeconds -> startSeconds - endSeconds
        setData.hasBeenExecuted && endSeconds <= 0 -> startSeconds
        setData.hasBeenExecuted && endSeconds == startSeconds -> startSeconds
        endSeconds > startSeconds -> endSeconds
        else -> 0
    }
}

private fun extractEnduranceDurationSeconds(
    setData: EnduranceSetData,
): Int {
    val elapsedSeconds = normalizeTimerValueToSeconds(setData.endTimer)
    val fallbackSeconds = normalizeTimerValueToSeconds(setData.startTimer)

    return when {
        elapsedSeconds > 0 -> elapsedSeconds
        setData.hasBeenExecuted && fallbackSeconds > 0 -> fallbackSeconds
        else -> 0
    }
}

private fun normalizeTimerValueToSeconds(
    rawValue: Int,
): Int = when {
    rawValue <= 0 -> 0
    rawValue >= 1_000 -> rawValue / 1_000
    else -> rawValue
}

private fun compareSessions(
    candidate: ComparableExerciseSession,
    baseline: ComparableExerciseSession,
    achievableWeights: List<Double>?,
): Int {
    val candidateMetrics = metricsForSetHistories(candidate.activeSetHistories, achievableWeights)
    val baselineMetrics = metricsForSetHistories(baseline.activeSetHistories, achievableWeights)

    if (candidateMetrics.simpleSets.isNotEmpty() && baselineMetrics.simpleSets.isNotEmpty()) {
        return when (compareSetListsUnordered(candidateMetrics.simpleSets, baselineMetrics.simpleSets)) {
            Ternary.ABOVE -> 1
            Ternary.BELOW -> -1
            Ternary.EQUAL, Ternary.MIXED -> compareMetricTotals(candidateMetrics, baselineMetrics)
        }
    }

    return compareMetricTotals(candidateMetrics, baselineMetrics)
}

private fun compareMetricTotals(
    candidate: ExportSessionMetrics,
    baseline: ExportSessionMetrics,
): Int {
    if (abs(candidate.totalVolume - baseline.totalVolume) > 0.001) {
        return if (candidate.totalVolume > baseline.totalVolume) 1 else -1
    }
    if (candidate.totalDurationSeconds != baseline.totalDurationSeconds) {
        return candidate.totalDurationSeconds.compareTo(baseline.totalDurationSeconds)
    }
    if (candidate.executedSetCount != baseline.executedSetCount) {
        return candidate.executedSetCount.compareTo(baseline.executedSetCount)
    }
    return 0
}

private fun compareSignal(
    prefix: String,
    selected: ComparableExerciseSession,
    baseline: ComparableExerciseSession,
    achievableWeights: List<Double>?,
): String {
    return when (compareSessions(selected, baseline, achievableWeights)) {
        1 -> "${prefix}:above"
        -1 -> "${prefix}:below"
        else -> "${prefix}:similar"
    }
}

private fun ternarySignal(prefix: String, value: Ternary): String {
    val suffix = when (value) {
        Ternary.ABOVE -> "above"
        Ternary.BELOW -> "below"
        Ternary.EQUAL -> "equal"
        Ternary.MIXED -> "mixed"
    }
    return "$prefix:$suffix"
}

private fun trendSignal(
    sessions: List<ComparableExerciseSession>,
    achievableWeights: List<Double>?,
): String? {
    val recent = sessions.takeLast(3)
    if (recent.size < 3) return null
    val values = recent.map { metrics ->
        val sessionMetrics = metricsForSetHistories(metrics.activeSetHistories, achievableWeights)
        if (sessionMetrics.totalVolume > 0.0) sessionMetrics.totalVolume else sessionMetrics.totalDurationSeconds.toDouble()
    }
    return when {
        values[0] < values[1] && values[1] < values[2] -> "trend:up"
        values[0] > values[1] && values[1] > values[2] -> "trend:down"
        abs(values[0] - values[1]) < 0.001 && abs(values[1] - values[2]) < 0.001 -> "trend:stable"
        else -> "trend:mixed"
    }
}
