package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.screens.resolveWorkoutPhaseRenderModel
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutScreenPhaseRenderModelTest {

    @Test
    fun resumingShowsOnlyDedicatedLoadingUi() {
        val model = resolveWorkoutPhaseRenderModel(
            sessionPhase = WorkoutSessionPhase.RESUMING,
            isRefreshing = false
        )

        assertEquals("Resuming your workout", model.loadingMessage)
        assertFalse(model.showHeader)
        assertFalse(model.renderPreparing)
        assertFalse(model.renderActiveContent)
        assertFalse(model.renderCompletedContent)
    }

    @Test
    fun activeShowsHeaderAndWorkoutContent() {
        val model = resolveWorkoutPhaseRenderModel(
            sessionPhase = WorkoutSessionPhase.ACTIVE,
            isRefreshing = false
        )

        assertTrue(model.showHeader)
        assertTrue(model.renderActiveContent)
        assertFalse(model.renderPreparing)
        assertFalse(model.renderCompletedContent)
    }

    @Test
    fun preparingKeepsPreparationContentAndHidesHeader() {
        val model = resolveWorkoutPhaseRenderModel(
            sessionPhase = WorkoutSessionPhase.PREPARING,
            isRefreshing = false
        )

        assertTrue(model.renderPreparing)
        assertFalse(model.showHeader)
        assertFalse(model.renderActiveContent)
        assertFalse(model.renderCompletedContent)
    }
}
