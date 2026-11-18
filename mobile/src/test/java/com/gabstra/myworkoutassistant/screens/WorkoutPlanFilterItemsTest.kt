package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.UUID

class WorkoutPlanFilterItemsTest {

    @Test
    fun namedPlansKeepTheirOrderAndNoPlanIsFilterOnly() {
        val push = plan("Push")
        val pull = plan("Pull")

        val items = workoutPlanFilterItems(listOf(push, pull), "No plan")

        assertEquals(listOf<UUID?>(push.id, pull.id, null), items.map { it.value })
        assertEquals(listOf("Push", "Pull", "No plan"), items.map { it.label })
    }

    @Test
    fun duplicatePlanIdsAreDeduplicatedAndNoSyntheticPlanIsAdded() {
        val push = plan("Push")

        val items = workoutPlanFilterItems(listOf(push, push), "No plan")

        assertEquals(listOf<UUID?>(push.id, null), items.map { it.value })
        assertEquals(listOf("Push", "No plan"), items.map { it.label })
    }

    private fun plan(name: String) = WorkoutPlan(
        id = UUID.randomUUID(),
        name = name,
        workoutIds = emptyList(),
        order = 0,
    )
}
