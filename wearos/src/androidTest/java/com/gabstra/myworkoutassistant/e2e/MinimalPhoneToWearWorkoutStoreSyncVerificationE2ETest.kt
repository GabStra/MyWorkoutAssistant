package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.MinimalCrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MinimalPhoneToWearWorkoutStoreSyncVerificationE2ETest {
    private fun resolvedSyncTimeoutMs(): Long = 45_000

    @Test
    fun phoneSync_sendsMinimalWorkoutDefinitionToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + resolvedSyncTimeoutMs()
        var exercise: Exercise? = null

        while (System.currentTimeMillis() < deadline && exercise == null) {
            exercise = repository.getWorkoutStore().workouts
                .firstOrNull {
                    it.id == MinimalCrossDeviceSyncWorkoutStoreFixture.WORKOUT_ID &&
                        it.globalId == MinimalCrossDeviceSyncWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                        it.name == MinimalCrossDeviceSyncWorkoutStoreFixture.WORKOUT_NAME
                }
                ?.workoutComponents
                ?.singleOrNull() as? Exercise
            if (exercise == null) {
                delay(500)
            }
        }

        val syncedExercise = exercise
            ?: error("Minimal synced workout definition was not found on Wear within timeout.")

        assertEquals(
            MinimalCrossDeviceSyncWorkoutStoreFixture.expectedSetIdsInOrder(),
            syncedExercise.sets.map { it.id }
        )
        assertTrue(syncedExercise.sets[0] is WeightSet)
        assertTrue(syncedExercise.sets[1] is RestSet)
        assertTrue(syncedExercise.sets[2] is WeightSet)
        assertTrue(syncedExercise.sets[3] is RestSet)
        assertTrue(syncedExercise.sets[4] is WeightSet)
    }
}
