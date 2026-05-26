package com.gabstra.myworkoutassistant.healthconnect.external

import com.gabstra.myworkoutassistant.WorkoutTypes
import java.time.Duration
import java.time.LocalDateTime

private const val DUPLICATE_SESSION_OVERLAP_RATIO_THRESHOLD = 0.8
private const val DUPLICATE_SESSION_TIME_DELTA_TOLERANCE_SECONDS = 15 * 60L

fun buildExternalHealthConnectSessionEntities(
    sessions: List<RawExternalExerciseSession>,
    heartRateSamples: List<RawExternalHeartRateSample>,
    appOwnedWorkoutHistoryIds: Set<String>,
    appOwnedSessionWindows: List<AppOwnedSessionWindow>,
    appPackageName: String,
    syncedAt: LocalDateTime,
    resolveSourceAppLabel: (String?) -> String?,
): List<ExternalHealthConnectSessionEntity> {
    val sortedSamples = heartRateSamples
        .asSequence()
        .filter { it.beatsPerMinute > 0 }
        .sortedBy { it.time }
        .toList()

    return sessions
        .sortedByDescending { it.startTime }
        .mapNotNull { session ->
            val isAppOwned =
                session.clientRecordId in appOwnedWorkoutHistoryIds ||
                    session.sourcePackageName == appPackageName
            if (isAppOwned || overlapsAppOwnedSession(session, appOwnedSessionWindows)) {
                return@mapNotNull null
            }

            val durationSeconds = Duration.between(session.startTime, session.endTime)
                .seconds
                .toInt()
                .coerceAtLeast(0)

            val sessionSamples = sortedSamples
                .filter { sample ->
                    !sample.time.isBefore(session.startTime) && !sample.time.isAfter(session.endTime)
                }
                .map { sample ->
                    ExternalHeartRateSample(
                        offsetSeconds = Duration.between(session.startTime, sample.time)
                            .seconds
                            .toInt()
                            .coerceAtLeast(0)
                            .coerceAtMost(durationSeconds),
                        beatsPerMinute = sample.beatsPerMinute,
                    )
                }
                .distinctBy { it.offsetSeconds to it.beatsPerMinute }
                .sortedBy { it.offsetSeconds }

            val normalizedSeries = normalizeExternalHeartRateSamples(
                samples = sessionSamples,
                durationSeconds = durationSeconds,
            )
            val validSeries = normalizedSeries.filter { it > 0 }

            ExternalHealthConnectSessionEntity(
                id = session.id,
                startTime = session.startTime,
                endTime = session.endTime,
                date = session.startTime.toLocalDate(),
                time = session.startTime.toLocalTime(),
                durationSeconds = durationSeconds,
                exerciseType = session.exerciseType,
                exerciseTypeLabel = resolveExerciseTypeLabel(session.exerciseType),
                title = session.title?.trim()?.takeIf { it.isNotEmpty() },
                sourcePackageName = session.sourcePackageName,
                sourceAppLabel = resolveSourceAppLabel(session.sourcePackageName),
                isAppOwned = false,
                lastSyncedAt = syncedAt,
                averageHeartRate = validSeries.average().takeIf { !it.isNaN() }?.toInt(),
                minHeartRate = validSeries.minOrNull(),
                maxHeartRate = validSeries.maxOrNull(),
                heartRateSampleCount = sessionSamples.size,
                hasHeartRateData = validSeries.isNotEmpty(),
                heartRateSamples = sessionSamples,
            )
        }
}

data class AppOwnedSessionWindow(
    val startTime: LocalDateTime,
    val endTime: LocalDateTime,
)

fun normalizeExternalHeartRateSamples(
    samples: List<ExternalHeartRateSample>,
    durationSeconds: Int,
): List<Int> {
    if (samples.isEmpty()) {
        return emptyList()
    }

    val normalizedDuration = durationSeconds.coerceAtLeast(samples.maxOf { it.offsetSeconds })
    val result = MutableList(normalizedDuration + 1) { 0 }
    val sortedSamples = samples
        .filter { it.beatsPerMinute > 0 }
        .sortedBy { it.offsetSeconds }
        .distinctBy { it.offsetSeconds }

    if (sortedSamples.isEmpty()) {
        return emptyList()
    }

    for ((index, sample) in sortedSamples.withIndex()) {
        val nextOffset = sortedSamples.getOrNull(index + 1)?.offsetSeconds ?: normalizedDuration + 1
        val endExclusive = nextOffset.coerceAtMost(normalizedDuration + 1)
        for (second in sample.offsetSeconds.coerceAtMost(normalizedDuration) until endExclusive) {
            result[second] = sample.beatsPerMinute
        }
    }

    return result
}

private fun resolveExerciseTypeLabel(exerciseType: Int): String {
    return runCatching { WorkoutTypes.GetNameFromInt(exerciseType) }
        .getOrElse { "Workout" }
}

private fun overlapsAppOwnedSession(
    session: RawExternalExerciseSession,
    appOwnedSessionWindows: List<AppOwnedSessionWindow>,
): Boolean {
    return appOwnedSessionWindows.any { appSession ->
        isClearlyDuplicateSession(
            externalStart = session.startTime,
            externalEnd = session.endTime,
            internalStart = appSession.startTime,
            internalEnd = appSession.endTime,
        )
    }
}

private fun isClearlyDuplicateSession(
    externalStart: LocalDateTime,
    externalEnd: LocalDateTime,
    internalStart: LocalDateTime,
    internalEnd: LocalDateTime,
): Boolean {
    val externalDurationSeconds = Duration.between(externalStart, externalEnd).seconds
    val internalDurationSeconds = Duration.between(internalStart, internalEnd).seconds
    if (externalDurationSeconds <= 0 || internalDurationSeconds <= 0) {
        return false
    }

    val overlapStart = maxOf(externalStart, internalStart)
    val overlapEnd = minOf(externalEnd, internalEnd)
    val overlapSeconds = Duration.between(overlapStart, overlapEnd).seconds
    if (overlapSeconds <= 0) {
        return false
    }

    val shorterDurationSeconds = minOf(externalDurationSeconds, internalDurationSeconds)
    val overlapRatio = overlapSeconds.toDouble() / shorterDurationSeconds.toDouble()
    val startDeltaSeconds = kotlin.math.abs(Duration.between(externalStart, internalStart).seconds)
    val endDeltaSeconds = kotlin.math.abs(Duration.between(externalEnd, internalEnd).seconds)

    return overlapRatio >= DUPLICATE_SESSION_OVERLAP_RATIO_THRESHOLD &&
        startDeltaSeconds <= DUPLICATE_SESSION_TIME_DELTA_TOLERANCE_SECONDS &&
        endDeltaSeconds <= DUPLICATE_SESSION_TIME_DELTA_TOLERANCE_SECONDS
}
