package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceInsertedSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MinimalInsertedSetPhoneToWearWorkoutStoreSyncVerificationE2ETest {
    private fun resolvedSyncTimeoutMs(): Long = 45_000

    @Test
    fun phoneSync_sendsMinimalInsertedSetWorkoutDefinitionToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + resolvedSyncTimeoutMs()
        var exercise: Exercise? = null

        while (System.currentTimeMillis() < deadline && exercise == null) {
            exercise = repository.getWorkoutStore().workouts
                .firstOrNull {
                    it.id == MinimalCrossDeviceInsertedSetWorkoutStoreFixture.WORKOUT_ID &&
                        it.globalId == MinimalCrossDeviceInsertedSetWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                        it.name == MinimalCrossDeviceInsertedSetWorkoutStoreFixture.WORKOUT_NAME
                }
                ?.workoutComponents
                ?.singleOrNull() as? Exercise
            if (exercise == null) {
                delay(500)
            }
        }

        val syncedExercise = exercise
            ?: error("Minimal inserted-set synced workout definition was not found on Wear within timeout.")

        assertEquals(
            MinimalCrossDeviceInsertedSetWorkoutStoreFixture.initialSetIdsInOrder(),
            syncedExercise.sets.map { it.id }
        )
        assertTrue(syncedExercise.sets.all { it is WeightSet })
    }
}
