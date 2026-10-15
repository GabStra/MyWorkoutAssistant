package com.gabstra.myworkoutassistant.shared.workout.progression

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.export.sliceHeartRateRecords
import com.gabstra.myworkoutassistant.shared.export.targetZoneBpmBounds
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.workout.model.isNormallyCompleted
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID

/** User-selected training policy, not a physiological readiness test. */
data class DurationProgressionConfig(
    val incrementMinutes: Int = 5,
    val maximumMinutes: Int = 60,
    val successfulSessionsRequired: Int = 3,
    val minimumZonePercent: Int = 90,
    val minimumCoveragePercent: Int = 90,
) {
    fun isValid(): Boolean = incrementMinutes in 1..60 && maximumMinutes in 1..1440 &&
        successfulSessionsRequired in 1..20 && minimumZonePercent in 1..100 &&
        minimumCoveragePercent in 1..100
}

/** Stored with the prescribed set and its execution, including across device sync/backups. */
data class DurationProgressionSnapshot(
    val cycleId: UUID? = null,
    val config: DurationProgressionConfig? = null,
    val baselineSeconds: Int = 0,
    val prescribedSeconds: Int = 0,
    val lowerHrBpm: Int = 0,
    val upperHrBpm: Int = 0,
    val equipmentId: UUID? = null,
    val previousSeconds: Int = 0,
    val decisionReason: String? = null,
    val qualifyingSessionIds: List<UUID> = emptyList(),
)

data class DurationSessionAssessment(
    val sessionId: UUID,
    val prescribedSeconds: Int,
    val coveragePercent: Double?,
    val zonePercent: Double?,
    val qualifies: Boolean,
    val reason: String,
)

data class DurationProgressionDecision(
    val exerciseName: String,
    val currentSeconds: Int,
    val nextSeconds: Int,
    val qualifyingSessions: Int,
    val config: DurationProgressionConfig,
    val assessments: List<DurationSessionAssessment>,
    val prescription: DurationProgressionSnapshot,
    val reason: String,
) {
    fun asFactBlock(): String = buildString {
        appendLine("FACT Duration progression for $exerciseName: current $currentSeconds seconds; next $nextSeconds seconds; $reason")
        appendLine("FACT Duration progression policy: increment ${config.incrementMinutes} minutes; ceiling ${config.maximumMinutes} minutes; ${config.successfulSessionsRequired} sessions required consecutively; minimum work HR coverage ${config.minimumCoveragePercent}%; minimum valid work samples in zone ${config.minimumZonePercent}%")
        appendLine("FACT Duration progression prescribed HR zone: ${prescription.lowerHrBpm}-${prescription.upperHrBpm} bpm")
        appendLine("FACT Qualifying sessions at current duration: $qualifyingSessions sessions; only sessions recorded under this unchanged policy and prescription qualify")
        assessments.forEach { assessment ->
            append("FACT Assessed session ${assessment.sessionId}: prescribed ${assessment.prescribedSeconds} seconds; ${assessment.reason}")
            assessment.coveragePercent?.let { append("; HR coverage at least ${it.toInt()}%") }
            assessment.zonePercent?.let { append("; valid work samples in zone at least ${it.toInt()}%") }
            appendLine()
        }
        appendLine("FACT This is a configured progression decision, not evidence of adaptation or recovery readiness.")
    }.trim()
}

fun Exercise.durationProgressionSet(): TimedDurationSet? {
    if (exerciseType != ExerciseType.COUNTDOWN || durationProgression?.isValid() != true ||
        lowerBoundMaxHRPercent == null || upperBoundMaxHRPercent == null) return null
    val workSets = sets.filterNot { it is RestSet }
    val set = workSets.singleOrNull() as? TimedDurationSet ?: return null
    // Weighted and distance/calorie-targeted work needs its own overload policy.
    return set.takeIf { it.timeInMillis > 0 && (it.targetWeight == null || it.targetWeight == 0.0) &&
        it.targetDistanceMeters == null && it.targetCalories == null }
}

fun assessDurationSession(
    history: WorkoutHistory,
    rows: List<SetHistory>,
    zone: IntRange,
    config: DurationProgressionConfig,
): DurationSessionAssessment {
    val row = rows.singleOrNull()
    val data = row?.setData as? TimedDurationSetData
    val seconds = (data?.startTimer ?: 0) / 1000
    fun unavailable(reason: String) = DurationSessionAssessment(history.id, seconds, null, null, false, reason)
    if (!history.isNormallyCompleted() || row == null || data == null || rows.any { it.skipped } ||
        !data.hasBeenExecuted || seconds <= 0 || data.endTimer > 0) {
        return unavailable("prescribed work was not completed normally")
    }
    if (data.actualWeight != null && data.actualWeight != 0.0) {
        return unavailable("recorded load differs from the unweighted duration prescription")
    }
    val start = row.startTime ?: return unavailable("work timestamps unavailable")
    val end = row.endTime ?: return unavailable("work timestamps unavailable")
    val elapsed = Duration.between(start, end).seconds
    if (elapsed <= 0) return unavailable("work timestamps unavailable")
    if (elapsed + 2 < seconds) return unavailable("recorded work duration is shorter than the prescription")
    val samples = sliceHeartRateRecords(history.startTime, history.heartBeatRecords, start, end).filter { it > 0 }
    val coverage = (samples.size * 100.0 / elapsed).coerceAtMost(100.0)
    val inZone = if (samples.isEmpty()) null else samples.count { it in zone } * 100.0 / samples.size
    val reason = when {
        coverage < config.minimumCoveragePercent -> "insufficient HR coverage; cannot assess"
        inZone == null || inZone < config.minimumZonePercent -> "work HR zone adherence below configured threshold"
        else -> "completed work with qualifying HR coverage and zone adherence"
    }
    return DurationSessionAssessment(history.id, seconds, coverage, inZone,
        coverage >= config.minimumCoveragePercent && inZone != null && inZone >= config.minimumZonePercent, reason)
}

/** Derive from retained prescriptions and execution; repeat calls never consume a success twice. */
suspend fun calculateDurationProgression(
    workout: Workout,
    exercise: Exercise,
    store: WorkoutStore,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    through: LocalDateTime = LocalDateTime.now(),
    recordedZone: IntRange? = null,
): DurationProgressionDecision? {
    val set = exercise.durationProgressionSet() ?: return null
    val config = exercise.durationProgression ?: return null
    val zone = recordedZone?.let { it.first to it.last } ?: targetZoneBpmBounds(exercise, store) ?: return null
    val versions = WorkoutManager.workoutVersionIds(workout, store.workouts).toSet()
    if (zone.first <= 0 || zone.second <= zone.first) return null
    val previousSnapshot = set.durationProgressionSnapshot
    val snapshot = previousSnapshot?.takeIf {
        it.cycleId != null && it.config == config && it.baselineSeconds > 0 &&
            it.prescribedSeconds == set.timeInMillis / 1000 &&
            it.lowerHrBpm == zone.first && it.upperHrBpm == zone.second &&
            it.equipmentId == exercise.equipmentId
    } ?: DurationProgressionSnapshot(UUID.randomUUID(), config, set.timeInMillis / 1000,
        set.timeInMillis / 1000, zone.first, zone.second, exercise.equipmentId)
    val histories = versions.flatMap { workoutHistoryDao.getWorkoutsByWorkoutId(it) }
        .distinctBy { it.id }.filter { it.isDone && it.startTime <= through }.sortedByDescending { it.startTime }
    val assessments = mutableListOf<DurationSessionAssessment>()
    val currentSeconds = set.timeInMillis / 1000
    var successes = 0
    for (history in histories) {
        val rows = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(history.id, exercise.id)
            .filterNot { it.setData is com.gabstra.myworkoutassistant.shared.setdata.RestSetData }
        val recordedSnapshot = (rows.singleOrNull()?.setData as? TimedDurationSetData)?.durationProgressionSnapshot
            ?: break
        if (recordedSnapshot.cycleId != snapshot.cycleId || recordedSnapshot.config != config ||
            recordedSnapshot.lowerHrBpm != zone.first || recordedSnapshot.upperHrBpm != zone.second) break
        val assessment = assessDurationSession(history, rows, zone.first..zone.second, config)
        if (assessment.prescribedSeconds != currentSeconds) break
        assessments += assessment
        if (!assessment.qualifies) break
        successes++
        if (successes >= config.successfulSessionsRequired) break
    }
    val next = if (successes >= config.successfulSessionsRequired) {
        minOf(currentSeconds + config.incrementMinutes * 60, config.maximumMinutes * 60)
            .coerceAtLeast(currentSeconds)
    } else currentSeconds
    val reason = when {
        currentSeconds >= config.maximumMinutes * 60 -> "hold: configured duration ceiling reached"
        next > currentSeconds -> "increase: $successes consecutive sessions met the configured criteria"
        assessments.firstOrNull()?.qualifies == false -> "hold: ${assessments.first().reason}"
        assessments.isEmpty() -> "hold: no comparable sessions recorded under this policy and duration"
        else -> "hold: $successes of ${config.successfulSessionsRequired} required consecutive qualifying sessions"
    }
    return DurationProgressionDecision(exercise.name, currentSeconds, next, successes, config, assessments,
        snapshot.copy(prescribedSeconds = next, previousSeconds = currentSeconds, decisionReason = reason,
            qualifyingSessionIds = assessments.filter { it.qualifies }.map { it.sessionId }), reason)
}

/** Keep old sessions tied to the duration they ran, even after the template advances. */
fun Exercise.withRecordedDurationPrescription(rows: List<SetHistory>): Exercise {
    val data = rows.filterNot { it.setData is com.gabstra.myworkoutassistant.shared.setdata.RestSetData }
        .singleOrNull()?.setData as? TimedDurationSetData ?: return this
    val snapshot = data.durationProgressionSnapshot ?: return this
    if (snapshot.config?.isValid() != true || data.startTimer <= 0) return this
    return copy(durationProgression = snapshot.config, sets = sets.map { set ->
        if (set is TimedDurationSet) set.copy(timeInMillis = data.startTimer,
            durationProgressionSnapshot = snapshot) else set
    })
}

/** Historical exports use the policy and prescription captured when that set actually ran. */
suspend fun durationProgressionDecisionsForSession(
    workout: Workout,
    history: WorkoutHistory,
    store: WorkoutStore,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
): List<DurationProgressionDecision> {
    val decisions = mutableListOf<DurationProgressionDecision>()
    for (exercise in workout.workoutComponents.filterIsInstance<Exercise>()) {
        val rows = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(history.id, exercise.id)
            .filterNot { it.setData is com.gabstra.myworkoutassistant.shared.setdata.RestSetData }
        val data = rows.singleOrNull()?.setData as? TimedDurationSetData ?: continue
        val snapshot = data.durationProgressionSnapshot ?: continue
        if (snapshot.config?.isValid() != true || snapshot.cycleId == null) continue
        val recordedExercise = exercise.withRecordedDurationPrescription(rows)
        calculateDurationProgression(workout, recordedExercise, store, workoutHistoryDao, setHistoryDao,
            through = history.startTime, recordedZone = snapshot.lowerHrBpm..snapshot.upperHrBpm)
            ?.let { decision ->
                if (history.isNormallyCompleted()) {
                    decisions += decision
                } else {
                    val reason = "hold: current session was not completed normally"
                    decisions += decision.copy(nextSeconds = decision.currentSeconds, qualifyingSessions = 0,
                        assessments = listOf(assessDurationSession(history, rows,
                            snapshot.lowerHrBpm..snapshot.upperHrBpm, snapshot.config)),
                        prescription = decision.prescription.copy(prescribedSeconds = decision.currentSeconds,
                            decisionReason = reason, qualifyingSessionIds = emptyList()), reason = reason)
                }
            }
    }
    return decisions
}
