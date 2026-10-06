package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionEntity
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID

enum class WorkoutCalendarActivityKind {
    NONE,
    APP_OR_MIXED,
    EXTERNAL_ONLY,
}

sealed interface WorkoutStatusSessionEntry {
    val date: LocalDate
    val startedAt: LocalDateTime
}

data class AppWorkoutStatusSessionEntry(
    val weeklyStatusWorkoutHistory: WeeklyStatusWorkoutHistory,
) : WorkoutStatusSessionEntry {
    override val date: LocalDate = weeklyStatusWorkoutHistory.workoutHistory.date
    override val startedAt: LocalDateTime = weeklyStatusWorkoutHistory.workoutHistory.startTime

    val workoutId: UUID = weeklyStatusWorkoutHistory.workout.id
}

data class ExternalWorkoutStatusSessionEntry(
    val session: ExternalHealthConnectSessionEntity,
) : WorkoutStatusSessionEntry {
    override val date: LocalDate = session.date
    override val startedAt: LocalDateTime = session.startTime

    val dedupeKey: String = buildString {
        append(session.exerciseType)
        append('|')
        append(session.title?.trim().orEmpty().lowercase())
        append('|')
        append(session.startTime)
        append('|')
        append(session.endTime)
    }
}

fun sortWorkoutStatusSessions(
    sessions: List<WorkoutStatusSessionEntry>,
): List<WorkoutStatusSessionEntry> = sessions.sortedBy { it.startedAt }

fun deduplicateWorkoutStatusSessions(
    sessions: List<WorkoutStatusSessionEntry>,
): List<WorkoutStatusSessionEntry> {
    if (sessions.isEmpty()) {
        return emptyList()
    }

    val deduped = mutableListOf<WorkoutStatusSessionEntry>()
    val seenExternalKeys = mutableSetOf<String>()

    sessions.forEach { session ->
        when (session) {
            is AppWorkoutStatusSessionEntry -> deduped += session
            is ExternalWorkoutStatusSessionEntry -> {
                if (seenExternalKeys.add(session.dedupeKey)) {
                    deduped += session
                }
            }
        }
    }

    return deduped
}

fun resolveWorkoutCalendarActivityKind(
    sessionsByDate: Map<LocalDate, List<WorkoutStatusSessionEntry>>?,
    date: LocalDate,
): WorkoutCalendarActivityKind {
    val daySessions = sessionsByDate?.get(date).orEmpty()
    if (daySessions.isEmpty()) {
        return WorkoutCalendarActivityKind.NONE
    }

    return if (daySessions.all { it is ExternalWorkoutStatusSessionEntry }) {
        WorkoutCalendarActivityKind.EXTERNAL_ONLY
    } else {
        WorkoutCalendarActivityKind.APP_OR_MIXED
    }
}
