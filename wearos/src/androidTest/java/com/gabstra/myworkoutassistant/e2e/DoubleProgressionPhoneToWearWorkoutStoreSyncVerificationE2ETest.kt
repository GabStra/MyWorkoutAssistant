package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgeFixture
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class DoubleProgressionPhoneToWearWorkoutStoreSyncVerificationE2ETest {
    private fun resolvedSyncTimeoutMs(): Long {
        val fastProfile = InstrumentationRegistry.getArguments()
            .getString("e2e_profile")
            ?.equals("fast", true) == true
        return if (fastProfile) 45_000 else 120_000
    }

    @Test
    fun phoneSync_sendsBaseDoubleProgressionWorkoutDefinitionToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + resolvedSyncTimeoutMs()
        var exercise: Exercise? = null

        while (System.currentTimeMillis() < deadline && exercise == null) {
            exercise = repository.getWorkoutStore().workouts
                .firstOrNull {
                    it.id == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID &&
                        it.name == DoubleProgressionRoundTripBadgeFixture.WORKOUT_NAME
                }
                ?.workoutComponents
                ?.singleOrNull() as? Exercise
            if (exercise == null) {
                delay(500)
            }
        }

        val syncedExercise = exercise
            ?: error("Double-progression round-trip workout definition was not found on Wear within timeout.")
        val syncedSet = syncedExercise.sets.single() as? WeightSet
            ?: error("Expected a single weight set in the synced workout definition.")

        assertEquals(DoubleProgressionRoundTripBadgeFixture.SET_ID, syncedSet.id)
        assertEquals(DoubleProgressionRoundTripBadgeFixture.PHONE_TEMPLATE_REPS, syncedSet.reps)
        assertTrue(abs(syncedSet.weight - DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT) <= DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE)
    }
}
