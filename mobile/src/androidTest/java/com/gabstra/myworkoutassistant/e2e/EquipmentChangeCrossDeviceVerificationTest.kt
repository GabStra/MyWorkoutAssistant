package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class EquipmentChangeCrossDeviceVerificationTest {
    private companion object {
        const val WORKOUT_NAME = "Weight Equipment Change Test Workout"
        const val EXERCISE_NAME = "Machine Press"
        const val EXPECTED_EQUIPMENT_NAME = "Test Barbell"
        const val SYNC_TIMEOUT_MS = 60_000L
    }

    @Test
    fun wearEquipmentChange_updatesPhoneWorkoutDefinition() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + SYNC_TIMEOUT_MS

        var observedEquipmentName: String? = null
        var observedExercise: Exercise? = null
        while (System.currentTimeMillis() < deadline) {
            val store = repository.getWorkoutStore()
            val workout = store.workouts.firstOrNull { it.name == WORKOUT_NAME }
            observedExercise = workout
                ?.workoutComponents
                ?.filterIsInstance<Exercise>()
                ?.firstOrNull { it.name == EXERCISE_NAME }
            observedEquipmentName = observedExercise
                ?.equipmentId
                ?.let { equipmentId -> store.equipments.firstOrNull { it.id == equipmentId } }
                ?.name
            if (observedEquipmentName == EXPECTED_EQUIPMENT_NAME) break
            delay(250)
        }

        assertNotNull("Phone did not receive workout '$WORKOUT_NAME' from Wear", observedExercise)
        assertEquals(
            "Phone exercise definition did not retain the equipment selected on Wear",
            EXPECTED_EQUIPMENT_NAME,
            observedEquipmentName
        )
    }
}
