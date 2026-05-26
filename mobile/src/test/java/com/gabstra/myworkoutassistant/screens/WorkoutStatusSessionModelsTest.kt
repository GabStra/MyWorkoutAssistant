package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionEntity
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WorkoutStatusSessionModelsTest {
    @Test
    fun buildWorkoutStatusRenderBlocks_keepsChronologicalOrderingWithExternalSessions() {
        val workout = testWorkout()
        val date = LocalDate.of(2026, 5, 20)

        val sessions = listOf(
            AppWorkoutStatusSessionEntry(
                WeeklyStatusWorkoutHistory(
                    workoutHistory = testWorkoutHistory(workout, date, LocalTime.of(10, 0)),
                    workout = workout,
                    isExcludedFromWeeklyProgress = false,
                )
            ),
            ExternalWorkoutStatusSessionEntry(
                session = testExternalSession(
                    id = "external-1",
                    date = date,
                    time = LocalTime.of(11, 0),
                )
            ),
            AppWorkoutStatusSessionEntry(
                WeeklyStatusWorkoutHistory(
                    workoutHistory = testWorkoutHistory(workout, date, LocalTime.of(12, 0)),
                    workout = workout,
                    isExcludedFromWeeklyProgress = false,
                )
            ),
        )

        val blocks = buildWorkoutStatusRenderBlocks(sessions)

        assertEquals(3, blocks.size)
        assertEquals("12:00", (blocks[0] as AppWorkoutStatusSessionGroup).sessions.single().startedAt.toLocalTime().toString().substring(0, 5))
        assertEquals("external-1", (blocks[1] as ExternalWorkoutStatusSessionBlock).session.session.id)
        assertEquals("10:00", (blocks[2] as AppWorkoutStatusSessionGroup).sessions.single().startedAt.toLocalTime().toString().substring(0, 5))
    }

    @Test
    fun buildWorkoutStatusRenderBlocks_groupsAdjacentAppSessionsForSameWorkout() {
        val workout = testWorkout()
        val date = LocalDate.of(2026, 5, 20)

        val blocks = buildWorkoutStatusRenderBlocks(
            listOf(
                AppWorkoutStatusSessionEntry(
                    WeeklyStatusWorkoutHistory(
                        workoutHistory = testWorkoutHistory(workout, date, LocalTime.of(12, 0)),
                        workout = workout,
                        isExcludedFromWeeklyProgress = false,
                    )
                ),
                AppWorkoutStatusSessionEntry(
                    WeeklyStatusWorkoutHistory(
                        workoutHistory = testWorkoutHistory(workout, date, LocalTime.of(11, 0)),
                        workout = workout,
                        isExcludedFromWeeklyProgress = false,
                    )
                ),
            )
        )

        assertEquals(1, blocks.size)
        assertEquals(2, (blocks.single() as AppWorkoutStatusSessionGroup).sessions.size)
    }

    @Test
    fun deduplicateWorkoutStatusSessions_collapsesRepeatedExternalEntries() {
        val date = LocalDate.of(2026, 5, 20)
        val externalOne = ExternalWorkoutStatusSessionEntry(
            session = testExternalSession(
                id = "external-1",
                date = date,
                time = LocalTime.of(11, 0),
                sourcePackageName = "com.example.one",
            )
        )
        val externalDuplicate = ExternalWorkoutStatusSessionEntry(
            session = testExternalSession(
                id = "external-2",
                date = date,
                time = LocalTime.of(11, 0),
                sourcePackageName = "com.example.two",
            )
        )

        val result = deduplicateWorkoutStatusSessions(listOf(externalOne, externalDuplicate))

        assertEquals(1, result.size)
        assertTrue(result.single() is ExternalWorkoutStatusSessionEntry)
    }

    @Test
    fun resolveWorkoutCalendarActivityKind_marksExternalOnlyDays() {
        val date = LocalDate.of(2026, 5, 20)
        val externalSession = ExternalWorkoutStatusSessionEntry(
            session = testExternalSession(
                id = "external-1",
                date = date,
                time = LocalTime.of(11, 0),
            )
        )

        val result = resolveWorkoutCalendarActivityKind(
            sessionsByDate = mapOf(date to listOf(externalSession)),
            date = date,
        )

        assertEquals(WorkoutCalendarActivityKind.EXTERNAL_ONLY, result)
    }

    private fun testWorkout(): Workout {
        return Workout(
            id = UUID.randomUUID(),
            name = "Upper A",
            description = "",
            workoutComponents = emptyList(),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 1, 1),
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            nextVersionId = null,
            type = 56,
            workoutPlanId = null,
        )
    }

    private fun testWorkoutHistory(
        workout: Workout,
        date: LocalDate,
        time: LocalTime,
    ): WorkoutHistory {
        return WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = workout.id,
            date = date,
            time = time,
            startTime = LocalDateTime.of(date, time),
            duration = 1200,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
            version = 0u,
        )
    }

    private fun testExternalSession(
        id: String,
        date: LocalDate,
        time: LocalTime,
        sourcePackageName: String = "com.example",
    ): ExternalHealthConnectSessionEntity {
        val start = LocalDateTime.of(date, time)
        return ExternalHealthConnectSessionEntity(
            id = id,
            startTime = start,
            endTime = start.plusMinutes(30),
            date = date,
            time = time,
            durationSeconds = 1800,
            exerciseType = 56,
            exerciseTypeLabel = "Running",
            title = "Lunch Run",
            sourcePackageName = sourcePackageName,
            sourceAppLabel = "Example",
            isAppOwned = false,
            lastSyncedAt = start.plusHours(1),
            averageHeartRate = 135,
            minHeartRate = 120,
            maxHeartRate = 150,
            heartRateSampleCount = 3,
            hasHeartRateData = true,
            heartRateSamples = emptyList(),
        )
    }
}
