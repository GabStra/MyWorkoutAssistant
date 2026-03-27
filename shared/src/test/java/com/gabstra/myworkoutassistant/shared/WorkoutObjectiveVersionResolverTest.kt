package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutObjectiveVersionResolverTest {

    private fun workout(
        id: UUID = UUID.randomUUID(),
        globalId: UUID,
        creationDate: LocalDate,
        timesCompletedInAWeek: Int?,
        enabled: Boolean = true,
        isActive: Boolean = true
    ): Workout = Workout(
        id = id,
        name = "Workout",
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        enabled = enabled,
        heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
        creationDate = creationDate,
        previousVersionId = null,
        nextVersionId = null,
        isActive = isActive,
        timesCompletedInAWeek = timesCompletedInAWeek,
        globalId = globalId,
        type = 0,
        workoutPlanId = null
    )

    @Test
    fun week1_usesVersionA_target() {
        val globalId = UUID.randomUUID()
        val monWeek1 = LocalDate.of(2025, 3, 3)
        val sunWeek1 = LocalDate.of(2025, 3, 9)
        val versionA = workout(globalId = globalId, creationDate = monWeek1, timesCompletedInAWeek = 2)

        val result = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA),
            weekEnd = sunWeek1
        )

        assertEquals(1, result.size)
        assertEquals(versionA.id, result[globalId]?.id)
        assertEquals(2, result[globalId]?.timesCompletedInAWeek)
    }

    @Test
    fun week2_afterEdit_usesVersionB() {
        val globalId = UUID.randomUUID()
        val monWeek1 = LocalDate.of(2025, 3, 3)
        val sunWeek1 = LocalDate.of(2025, 3, 9)
        val monWeek2 = LocalDate.of(2025, 3, 10)
        val sunWeek2 = LocalDate.of(2025, 3, 16)
        val versionA = workout(globalId = globalId, creationDate = monWeek1, timesCompletedInAWeek = 2, isActive = false)
        val versionB = workout(globalId = globalId, creationDate = monWeek2, timesCompletedInAWeek = 3, isActive = true)

        val resultWeek1 = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA, versionB),
            weekEnd = sunWeek1
        )
        val resultWeek2 = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA, versionB),
            weekEnd = sunWeek2
        )

        assertEquals(versionA.id, resultWeek1[globalId]?.id)
        assertEquals(2, resultWeek1[globalId]?.timesCompletedInAWeek)
        assertEquals(versionB.id, resultWeek2[globalId]?.id)
        assertEquals(3, resultWeek2[globalId]?.timesCompletedInAWeek)
    }

    @Test
    fun weeks3And4_withNoEdit_reuseVersionB() {
        val globalId = UUID.randomUUID()
        val monWeek2 = LocalDate.of(2025, 3, 10)
        val sunWeek2 = LocalDate.of(2025, 3, 16)
        val sunWeek3 = LocalDate.of(2025, 3, 23)
        val sunWeek4 = LocalDate.of(2025, 3, 30)
        val versionA = workout(globalId = globalId, creationDate = LocalDate.of(2025, 3, 3), timesCompletedInAWeek = 2, isActive = false)
        val versionB = workout(globalId = globalId, creationDate = monWeek2, timesCompletedInAWeek = 3, isActive = true)

        val resultWeek3 = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA, versionB),
            weekEnd = sunWeek3
        )
        val resultWeek4 = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA, versionB),
            weekEnd = sunWeek4
        )

        assertEquals(versionB.id, resultWeek3[globalId]?.id)
        assertEquals(3, resultWeek3[globalId]?.timesCompletedInAWeek)
        assertEquals(versionB.id, resultWeek4[globalId]?.id)
        assertEquals(3, resultWeek4[globalId]?.timesCompletedInAWeek)
    }

    @Test
    fun editOnWednesdayOfWeek5_week5UsesNewTarget() {
        val globalId = UUID.randomUUID()
        val monWeek5 = LocalDate.of(2025, 4, 7)
        val wedWeek5 = LocalDate.of(2025, 4, 9)
        val sunWeek5 = LocalDate.of(2025, 4, 13)
        val versionA = workout(globalId = globalId, creationDate = LocalDate.of(2025, 3, 3), timesCompletedInAWeek = 2, isActive = false)
        val versionB = workout(globalId = globalId, creationDate = wedWeek5, timesCompletedInAWeek = 4, isActive = true)

        val resultWeek5 = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA, versionB),
            weekEnd = sunWeek5
        )

        assertEquals(versionB.id, resultWeek5[globalId]?.id)
        assertEquals(4, resultWeek5[globalId]?.timesCompletedInAWeek)
    }

    @Test
    fun excludesDisabledWorkouts() {
        val globalId = UUID.randomUUID()
        val sunWeek = LocalDate.of(2025, 3, 9)
        val versionA = workout(globalId = globalId, creationDate = sunWeek, timesCompletedInAWeek = 2, enabled = false)

        val result = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(versionA),
            weekEnd = sunWeek
        )

        assertEquals(0, result.size)
    }

    @Test
    fun excludesZeroOrNullObjective() {
        val globalId = UUID.randomUUID()
        val sunWeek = LocalDate.of(2025, 3, 9)
        val withNull = workout(globalId = globalId, creationDate = sunWeek, timesCompletedInAWeek = null)
        val withZero = workout(globalId = UUID.randomUUID(), creationDate = sunWeek, timesCompletedInAWeek = 0)

        val result = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(withNull, withZero),
            weekEnd = sunWeek
        )

        assertEquals(0, result.size)
    }

    @Test
    fun multipleFamilies_resolvedIndependently() {
        val global1 = UUID.randomUUID()
        val global2 = UUID.randomUUID()
        val monWeek1 = LocalDate.of(2025, 3, 3)
        val sunWeek2 = LocalDate.of(2025, 3, 16)
        val v1a = workout(globalId = global1, creationDate = monWeek1, timesCompletedInAWeek = 2)
        val v2a = workout(globalId = global2, creationDate = monWeek1, timesCompletedInAWeek = 3)
        val v2b = workout(globalId = global2, creationDate = LocalDate.of(2025, 3, 10), timesCompletedInAWeek = 4, isActive = true)

        val result = WorkoutObjectiveVersionResolver.effectiveObjectiveVersionsForWeek(
            workouts = listOf(v1a, v2a, v2b),
            weekEnd = sunWeek2
        )

        assertEquals(2, result.size)
        assertEquals(v1a.id, result[global1]?.id)
        assertEquals(2, result[global1]?.timesCompletedInAWeek)
        assertEquals(v2b.id, result[global2]?.id)
        assertEquals(4, result[global2]?.timesCompletedInAWeek)
    }
}
