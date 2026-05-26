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

sealed interface WorkoutStatusSessionRenderBlock

data class AppWorkoutStatusSessionGroup(
    val sessions: List<AppWorkoutStatusSessionEntry>,
) : WorkoutStatusSessionRenderBlock

data class ExternalWorkoutStatusSessionBlock(
    val session: ExternalWorkoutStatusSessionEntry,
) : WorkoutStatusSessionRenderBlock

fun buildWorkoutStatusRenderBlocks(
    sessions: List<WorkoutStatusSessionEntry>,
): List<WorkoutStatusSessionRenderBlock> {
    if (sessions.isEmpty()) {
        return emptyList()
    }

    val sortedSessions = sessions.sortedBy { it.startedAt }
    val blocks = mutableListOf<WorkoutStatusSessionRenderBlock>()

    sortedSessions.forEach { session ->
        when (session) {
            is AppWorkoutStatusSessionEntry -> {
                val lastGroup = blocks.lastOrNull() as? AppWorkoutStatusSessionGroup
                if (
                    lastGroup != null &&
                    lastGroup.sessions.first().workoutId == session.workoutId
                ) {
                    blocks[blocks.lastIndex] = lastGroup.copy(
                        sessions = lastGroup.sessions + session,
                    )
                } else {
                    blocks += AppWorkoutStatusSessionGroup(listOf(session))
                }
            }

            is ExternalWorkoutStatusSessionEntry -> {
                blocks += ExternalWorkoutStatusSessionBlock(session)
            }
        }
    }

    return blocks
}

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
