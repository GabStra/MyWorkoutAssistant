package com.gabstra.myworkoutassistant.healthconnect.external

import com.gabstra.myworkoutassistant.WorkoutTypes
import java.security.MessageDigest
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

    val externalSessions = sessions.filterNot { session ->
            val isAppOwned =
                session.clientRecordId in appOwnedWorkoutHistoryIds ||
                    session.sourcePackageName == appPackageName
            isAppOwned || overlapsAppOwnedSession(session, appOwnedSessionWindows)
        }

    return mergeOverlappingExternalSessions(externalSessions, resolveSourceAppLabel)
        .sortedByDescending { it.session.startTime }
        .map { mergedSession ->
            val session = mergedSession.session

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
                sourceAppLabel = mergedSession.sourceAppLabel,
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

private data class MergedExternalExerciseSession(
    val session: RawExternalExerciseSession,
    val sourceAppLabel: String?,
)

private fun mergeOverlappingExternalSessions(
    sessions: List<RawExternalExerciseSession>,
    resolveSourceAppLabel: (String?) -> String?,
): List<MergedExternalExerciseSession> {
    if (sessions.isEmpty()) return emptyList()

    val sortedSessions = sessions.sortedWith(
        compareBy<RawExternalExerciseSession> { it.startTime }
            .thenBy { it.endTime }
            .thenBy { it.id }
    )
    val groups = mutableListOf<MutableList<RawExternalExerciseSession>>()
    var currentGroup = mutableListOf(sortedSessions.first())
    var currentGroupEnd = sortedSessions.first().endTime

    sortedSessions.drop(1).forEach { session ->
        val overlapsCurrentGroup =
            session.startTime.isBefore(currentGroupEnd) &&
                session.endTime.isAfter(currentGroup.minOf { it.startTime })

        if (overlapsCurrentGroup) {
            currentGroup += session
            currentGroupEnd = maxOf(currentGroupEnd, session.endTime)
        } else {
            groups += currentGroup
            currentGroup = mutableListOf(session)
            currentGroupEnd = session.endTime
        }
    }
    groups += currentGroup

    return groups.map { group ->
        val representative = group.maxWithOrNull(
            compareBy<RawExternalExerciseSession> {
                Duration.between(it.startTime, it.endTime).seconds
            }.thenBy { it.title?.isNotBlank() == true }
        ) ?: group.first()
        val sourcePackages = group.map { it.sourcePackageName }.distinct()
        val sourcePackageName = sourcePackages.singleOrNull()
        val sourceAppLabel = when {
            sourcePackages.size > 1 -> "Multiple sources"
            else -> resolveSourceAppLabel(sourcePackageName)
        }
        val mergedTitle = sequenceOf(representative)
            .plus(group.asSequence())
            .mapNotNull { it.title?.trim()?.takeIf(String::isNotEmpty) }
            .firstOrNull()
        val mergedId = if (group.size == 1) {
            representative.id
        } else {
            stableMergedSessionId(group.map { it.id })
        }

        MergedExternalExerciseSession(
            session = representative.copy(
                id = mergedId,
                clientRecordId = null,
                title = mergedTitle,
                startTime = group.minOf { it.startTime },
                endTime = group.maxOf { it.endTime },
                sourcePackageName = sourcePackageName,
            ),
            sourceAppLabel = sourceAppLabel,
        )
    }
}

private fun stableMergedSessionId(sourceIds: List<String>): String {
    val canonicalIds = sourceIds.sorted().joinToString(separator = "\u0000")
    val digest = MessageDigest.getInstance("SHA-256")
        .digest(canonicalIds.toByteArray(Charsets.UTF_8))
        .joinToString(separator = "") { byte ->
            (byte.toInt() and 0xff).toString(16).padStart(2, '0')
        }
    return "merged:$digest"
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
