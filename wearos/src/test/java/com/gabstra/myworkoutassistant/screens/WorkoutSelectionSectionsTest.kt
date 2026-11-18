package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutSelectionSectionsTest {

    @Test
    fun `unassigned sentinel plan renders as one trailing headerless section`() {
        val strengthPlanId = UUID.randomUUID()
        val unassignedPlanId = UUID.randomUUID()
        val plans = listOf(
            plan(strengthPlanId, name = "Strength", order = 0),
            plan(unassignedPlanId, name = UNASSIGNED_PLAN_NAME, order = 1),
        )
        val workouts = listOf(
            workout(name = "Loose", order = 1, planId = unassignedPlanId),
            workout(name = "Squat", order = 1, planId = strengthPlanId),
        )

        val sections = buildWorkoutSelectionSections(workouts, plans, visiblePlanIds = null)

        assertEquals(2, sections.size)
        assertEquals("Strength", sections[0].plan?.name)
        assertEquals(listOf("Squat"), sections[0].workouts.map { it.name })
        assertNull(sections[1].plan)
        assertEquals(listOf("Loose"), sections[1].workouts.map { it.name })
    }

    @Test
    fun `missing plans stay separate while hidden plans are omitted`() {
        val visiblePlanId = UUID.randomUUID()
        val hiddenPlanId = UUID.randomUUID()
        val plans = listOf(
            plan(visiblePlanId, name = "Push", order = 0),
            plan(hiddenPlanId, name = "Hidden", order = 1),
        )
        val workouts = listOf(
            workout(name = "Planless", order = 2, planId = null),
            workout(name = "MissingPlan", order = 0, planId = UUID.randomUUID()),
            workout(name = "HiddenWorkout", order = 0, planId = hiddenPlanId),
            workout(name = "VisibleWorkout", order = 0, planId = visiblePlanId),
        )

        val sections = buildWorkoutSelectionSections(
            workouts = workouts,
            plans = plans,
            visiblePlanIds = setOf(visiblePlanId),
        )

        assertEquals(2, sections.size)
        assertEquals("Push", sections[0].plan?.name)
        assertEquals(listOf("VisibleWorkout"), sections[0].workouts.map { it.name })
        assertNull(sections[1].plan)
        assertEquals(listOf("MissingPlan", "Planless"), sections[1].workouts.map { it.name })
    }

    @Test
    fun `hidden placeholder plan still exposes its workouts as ungrouped`() {
        val strengthPlanId = UUID.randomUUID()
        val unassignedPlanId = UUID.randomUUID()
        val plans = listOf(
            plan(strengthPlanId, name = "Strength", order = 0),
            plan(unassignedPlanId, name = UNASSIGNED_PLAN_NAME, order = 1),
        )
        val workouts = listOf(
            workout(name = "Legacy", order = 1, planId = unassignedPlanId),
            workout(name = "Squat", order = 0, planId = strengthPlanId),
        )

        val sections = buildWorkoutSelectionSections(
            workouts = workouts,
            plans = plans,
            visiblePlanIds = setOf(strengthPlanId),
        )

        assertEquals(2, sections.size)
        assertEquals("Strength", sections[0].plan?.name)
        assertEquals(listOf("Squat"), sections[0].workouts.map { it.name })
        assertNull(sections[1].plan)
        assertEquals(listOf("Legacy"), sections[1].workouts.map { it.name })
    }

    @Test
    fun `hidden real plan keeps its workouts hidden`() {
        val visiblePlanId = UUID.randomUUID()
        val hiddenPlanId = UUID.randomUUID()
        val plans = listOf(
            plan(visiblePlanId, name = "Push", order = 0),
            plan(hiddenPlanId, name = "Hidden", order = 1),
        )
        val workouts = listOf(
            workout(name = "VisibleWorkout", order = 0, planId = visiblePlanId),
            workout(name = "HiddenWorkout", order = 0, planId = hiddenPlanId),
        )

        val sections = buildWorkoutSelectionSections(
            workouts = workouts,
            plans = plans,
            visiblePlanIds = setOf(visiblePlanId),
        )

        assertEquals(1, sections.size)
        assertEquals(listOf("VisibleWorkout"), sections.single().workouts.map { it.name })
    }

    @Test
    fun `empty visibility keeps ungrouped workouts and hides all real plans`() {
        val planId = UUID.randomUUID()
        val plans = listOf(plan(planId, name = "Strength", order = 0))
        val workouts = listOf(
            workout(name = "Planless", order = 1, planId = null),
            workout(name = "Planned", order = 0, planId = planId),
        )

        val sections = buildWorkoutSelectionSections(
            workouts = workouts,
            plans = plans,
            visiblePlanIds = emptySet(),
        )

        assertEquals(1, sections.size)
        assertNull(sections.single().plan)
        assertEquals(listOf("Planless"), sections.single().workouts.map { it.name })
    }

    @Test
    fun `reserved placeholder plans render each workout exactly once`() {
        val strengthPlanId = UUID.randomUUID()
        val firstUnassignedPlanId = UUID.randomUUID()
        val secondUnassignedPlanId = UUID.randomUUID()
        val plans = listOf(
            plan(strengthPlanId, name = "Strength", order = 0),
            plan(firstUnassignedPlanId, name = UNASSIGNED_PLAN_NAME, order = 1),
            plan(secondUnassignedPlanId, name = UNASSIGNED_PLAN_NAME, order = 2),
        )
        val workouts = listOf(
            workout(name = "Planless", order = 3, planId = null),
            workout(name = "FirstLegacy", order = 2, planId = firstUnassignedPlanId),
            workout(name = "SecondLegacy", order = 1, planId = secondUnassignedPlanId),
            workout(name = "Squat", order = 0, planId = strengthPlanId),
        )

        val sections = buildWorkoutSelectionSections(
            workouts = workouts,
            plans = plans,
            visiblePlanIds = null,
        )

        val displayedIds = sections.flatMap { section -> section.workouts.map { it.id } }
        assertEquals(workouts.size, displayedIds.size)
        assertEquals(workouts.map { it.id }.toSet(), displayedIds.toSet())
        assertEquals(2, sections.size)
        assertEquals(listOf("Squat"), sections[0].workouts.map { it.name })
        assertNull(sections[1].plan)
        assertEquals(
            listOf("SecondLegacy", "FirstLegacy", "Planless"),
            sections[1].workouts.map { it.name },
        )
    }

    private fun plan(id: UUID, name: String, order: Int) = WorkoutPlan(
        id = id,
        name = name,
        workoutIds = emptyList(),
        order = order,
    )

    private fun workout(name: String, order: Int, planId: UUID?) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = order,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        workoutPlanId = planId,
    )
}
