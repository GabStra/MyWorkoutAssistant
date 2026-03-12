package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WeeklyProgressResolverTest {

    private fun workout(
        id: UUID = UUID.randomUUID(),
        globalId: UUID = UUID.randomUUID(),
        creationDate: LocalDate,
        target: Int,
        enabled: Boolean = true,
        isActive: Boolean = true,
        order: Int = 0,
        name: String = "Workout"
    ): Workout = Workout(
        id = id,
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = order,
        enabled = enabled,
        usePolarDevice = false,
        creationDate = creationDate,
        previousVersionId = null,
        nextVersionId = null,
        isActive = isActive,
        timesCompletedInAWeek = target,
        globalId = globalId,
        type = 0,
        workoutPlanId = null
    )

    private fun history(
        workoutId: UUID,
        globalId: UUID,
        date: LocalDate,
        isDone: Boolean = true
    ): WorkoutHistory = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        date = date,
        time = LocalTime.NOON,
        startTime = LocalDateTime.of(date, LocalTime.NOON),
        duration = 0,
        heartBeatRecords = emptyList(),
        isDone = isDone,
        hasBeenSentToHealth = false,
        globalId = globalId,
        version = 0u
    )

    @Test
    fun noOverride_preservesDefaultWeeklyProgressComputation() {
        val weekEnd = LocalDate.of(2025, 3, 9)
        val workoutA = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 2,
            order = 0,
            name = "A"
        )
        val workoutB = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 1,
            order = 1,
            name = "B"
        )

        val snapshot = WeeklyProgressResolver.resolveForWeek(
            workouts = listOf(workoutA, workoutB),
            workoutHistoriesInWeek = listOf(
                history(workoutA.id, workoutA.globalId, LocalDate.of(2025, 3, 3)),
                history(workoutA.id, workoutA.globalId, LocalDate.of(2025, 3, 5)),
                history(workoutB.id, workoutB.globalId, LocalDate.of(2025, 3, 7)),
            ),
            weekStart = LocalDate.of(2025, 3, 3),
            weekEnd = weekEnd,
            weeklyProgressOverrides = emptyList()
        )

        assertEquals(2, snapshot.weeklyWorkoutsByActualTarget.size)
        assertEquals(2 to 2, snapshot.weeklyWorkoutsByActualTarget[workoutA])
        assertEquals(1 to 1, snapshot.weeklyWorkoutsByActualTarget[workoutB])
        assertEquals(1.0, snapshot.objectiveProgress, 0.0)
        assertEquals(setOf(workoutA.globalId, workoutB.globalId), snapshot.includedWorkoutGlobalIds)
        assertTrue(snapshot.excludedWorkoutGlobalIds.isEmpty())
        assertTrue(!snapshot.hasOverride)
    }

    @Test
    fun includeOnlyOverride_excludesUnselectedWorkoutFamilies() {
        val weekEnd = LocalDate.of(2025, 3, 9)
        val workoutA = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 2,
            order = 0,
            name = "A"
        )
        val workoutB = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 1,
            order = 1,
            name = "B"
        )

        val snapshot = WeeklyProgressResolver.resolveForWeek(
            workouts = listOf(workoutA, workoutB),
            workoutHistoriesInWeek = listOf(
                history(workoutA.id, workoutA.globalId, LocalDate.of(2025, 3, 3)),
                history(workoutB.id, workoutB.globalId, LocalDate.of(2025, 3, 7)),
            ),
            weekStart = LocalDate.of(2025, 3, 3),
            weekEnd = weekEnd,
            weeklyProgressOverrides = listOf(
                WeeklyProgressOverride(
                    weekStart = LocalDate.of(2025, 3, 3),
                    includedWorkoutGlobalIds = listOf(workoutA.globalId)
                )
            )
        )

        assertEquals(1, snapshot.weeklyWorkoutsByActualTarget.size)
        assertEquals(1 to 2, snapshot.weeklyWorkoutsByActualTarget[workoutA])
        assertEquals(0.5, snapshot.objectiveProgress, 0.0)
        assertEquals(setOf(workoutA.globalId), snapshot.includedWorkoutGlobalIds)
        assertEquals(setOf(workoutB.globalId), snapshot.excludedWorkoutGlobalIds)
        assertTrue(snapshot.hasOverride)
        assertTrue(snapshot.isOverrideBoundary)
    }

    @Test
    fun overrideUsesGlobalIdWhenEffectiveWorkoutVersionChanges() {
        val globalId = UUID.randomUUID()
        val weekEnd = LocalDate.of(2025, 3, 16)
        val versionA = workout(
            globalId = globalId,
            creationDate = LocalDate.of(2025, 3, 3),
            target = 2,
            isActive = false,
            name = "Version A"
        )
        val versionB = workout(
            globalId = globalId,
            creationDate = LocalDate.of(2025, 3, 10),
            target = 3,
            isActive = true,
            name = "Version B"
        )

        val snapshot = WeeklyProgressResolver.resolveForWeek(
            workouts = listOf(versionA, versionB),
            workoutHistoriesInWeek = listOf(
                history(versionA.id, globalId, LocalDate.of(2025, 3, 11))
            ),
            weekStart = LocalDate.of(2025, 3, 10),
            weekEnd = weekEnd,
            weeklyProgressOverrides = listOf(
                WeeklyProgressOverride(
                    weekStart = LocalDate.of(2025, 3, 10),
                    includedWorkoutGlobalIds = listOf(globalId)
                )
            )
        )

        assertEquals(1 to 3, snapshot.weeklyWorkoutsByActualTarget[versionB])
        assertEquals(setOf(globalId), snapshot.includedWorkoutGlobalIds)
    }

    @Test
    fun emptySelectionOverride_resultsInZeroProgress() {
        val weekEnd = LocalDate.of(2025, 3, 9)
        val workoutA = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 2,
            name = "A"
        )
        val workoutB = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 1,
            name = "B"
        )

        val snapshot = WeeklyProgressResolver.resolveForWeek(
            workouts = listOf(workoutA, workoutB),
            workoutHistoriesInWeek = listOf(
                history(workoutA.id, workoutA.globalId, LocalDate.of(2025, 3, 3)),
                history(workoutB.id, workoutB.globalId, LocalDate.of(2025, 3, 7)),
            ),
            weekStart = LocalDate.of(2025, 3, 3),
            weekEnd = weekEnd,
            weeklyProgressOverrides = listOf(
                WeeklyProgressOverride(
                    weekStart = LocalDate.of(2025, 3, 3),
                    includedWorkoutGlobalIds = emptyList()
                )
            )
        )

        assertTrue(snapshot.weeklyWorkoutsByActualTarget.isEmpty())
        assertEquals(0.0, snapshot.objectiveProgress, 0.0)
        assertEquals(setOf(workoutA.globalId, workoutB.globalId), snapshot.excludedWorkoutGlobalIds)
        assertTrue(snapshot.includedWorkoutGlobalIds.isEmpty())
    }

    @Test
    fun latestPriorOverride_appliesUntilReplaced() {
        val weekStart = LocalDate.of(2025, 3, 10)
        val weekEnd = LocalDate.of(2025, 3, 16)
        val workoutA = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 2,
            order = 0,
            name = "A"
        )
        val workoutB = workout(
            globalId = UUID.randomUUID(),
            creationDate = LocalDate.of(2025, 3, 3),
            target = 1,
            order = 1,
            name = "B"
        )

        val snapshot = WeeklyProgressResolver.resolveForWeek(
            workouts = listOf(workoutA, workoutB),
            workoutHistoriesInWeek = listOf(
                history(workoutA.id, workoutA.globalId, LocalDate.of(2025, 3, 10)),
                history(workoutB.id, workoutB.globalId, LocalDate.of(2025, 3, 11)),
            ),
            weekStart = weekStart,
            weekEnd = weekEnd,
            weeklyProgressOverrides = listOf(
                WeeklyProgressOverride(
                    weekStart = LocalDate.of(2025, 3, 3),
                    includedWorkoutGlobalIds = listOf(workoutA.globalId)
                ),
                WeeklyProgressOverride(
                    weekStart = LocalDate.of(2025, 3, 17),
                    includedWorkoutGlobalIds = listOf(workoutB.globalId)
                )
            )
        )

        assertEquals(setOf(workoutA.globalId), snapshot.includedWorkoutGlobalIds)
        assertEquals(LocalDate.of(2025, 3, 3), snapshot.effectiveOverrideWeekStart)
        assertTrue(!snapshot.isOverrideBoundary)
    }
}
