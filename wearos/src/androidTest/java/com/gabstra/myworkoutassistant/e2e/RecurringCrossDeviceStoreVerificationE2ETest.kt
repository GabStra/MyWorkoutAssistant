package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.RecurringCrossDeviceFixture
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Verifies the actual imported Wear store, including both ordered recurring prescriptions. */
@RunWith(AndroidJUnit4::class)
class RecurringCrossDeviceStoreVerificationE2ETest {

    @Test
    fun phoneSyncRetainsRecurringFamilyOrderTracksPoliciesAndPlanSuggestionSetting() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val runId = requiredRunId()
        val profileId = RecurringCrossDeviceFixture.profileId(runId)
        assertTrue(
            "Phone sync did not publish the test profile index entry",
            Profiles.profiles(context).any { it.id == profileId },
        )

        val store = WorkoutStoreRepository(Profiles.directory(context, profileId), context.filesDir)
            .getWorkoutStore()
        val plan = store.workoutPlans.single { it.id == RecurringCrossDeviceFixture.planId(runId) }
        assertEquals(false, plan.suggestNextPrescription)

        val family = store.workouts
            .filter { it.recurringSessionId == RecurringCrossDeviceFixture.sessionId(runId) }
            .sortedBy { it.prescriptionOrdinal }
        assertEquals(2, family.size)
        assertEquals(
            listOf(RecurringCrossDeviceFixture.workoutId(runId, 1), RecurringCrossDeviceFixture.workoutId(runId, 2)),
            family.map { it.id },
        )
        assertEquals(family.map { it.id }, plan.workoutIds)
        assertEquals(listOf(1, 2), family.map { it.prescriptionOrdinal })
        assertEquals(
            listOf(
                RecurringCrossDeviceFixture.FOUNDATION_LABEL,
                RecurringCrossDeviceFixture.PROGRESSION_LABEL,
            ),
            family.map { it.prescriptionLabel },
        )
        assertTrue(family.all { it.name == RecurringCrossDeviceFixture.FAMILY_NAME && it.isActive })
        assertEquals(null, family[0].nextVersionId)
        assertEquals(null, family[1].previousVersionId)
        assertNotEquals(family[0].globalId, family[1].globalId)

        for (slot in RecurringCrossDeviceFixture.Slot.values()) {
            val trackId = RecurringCrossDeviceFixture.trackId(runId, slot)
            val definitionId = RecurringCrossDeviceFixture.definitionId(runId, slot)
            val exercises = family.map { workout ->
                workout.workoutComponents.filterIsInstance<Exercise>()
                    .single { it.recurringExerciseId == trackId }
            }
            assertEquals(listOf(slot.policy, slot.policy), exercises.map { it.loadHistoryPolicy })
            assertEquals(listOf(definitionId, definitionId), exercises.map { it.exerciseDefinitionId })
            assertEquals(listOf(ExerciseType.WEIGHT, ExerciseType.WEIGHT), exercises.map { it.exerciseType })
            assertEquals(2, exercises.map { it.id }.distinct().size)
            assertEquals(2, exercises.map { it.sets.single().id }.distinct().size)
        }
        assertEquals(3, family.flatMap { workout ->
            workout.workoutComponents.filterIsInstance<Exercise>().mapNotNull { it.recurringExerciseId }
        }.distinct().size)
        assertNotNull(store.exerciseDefinitions.singleOrNull { it.id == RecurringCrossDeviceFixture.definitionId(runId, RecurringCrossDeviceFixture.Slot.NONE) })
    }

    private fun requiredRunId(): String = requireNotNull(
        InstrumentationRegistry.getArguments().getString("run_id")
    ) { "The recurring cross-device runner must provide the run_id instrumentation argument." }
}
