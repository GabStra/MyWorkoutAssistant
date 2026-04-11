package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.StartupRestoreBackupFixture
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.loadLatestBackupFromDownloads
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StartupRestoreFromDownloadsVerificationTest {
    private companion object {
        const val RESTORE_TIMEOUT_MS = 30_000L
        const val POLL_INTERVAL_MS = 500L
    }

    @Test
    fun firstLaunchRestoresExistingManualDownloadsBackup() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val driver = PhoneAppDriver(device, context)

        assertTrue(
            "Expected fresh app data before startup restore.",
            WorkoutStoreRepository(context.filesDir).getWorkoutStore().workouts.isEmpty()
        )
        val stagedBackup = loadLatestBackupFromDownloads(context)
            ?: error("Expected a valid manual backup to be discoverable from Downloads before first launch.")
        assertTrue(
            "Expected staged Downloads backup to contain ${StartupRestoreBackupFixture.WORKOUT_NAME}.",
            stagedBackup.WorkoutStore.workouts.any { workout ->
                workout.id == StartupRestoreBackupFixture.WORKOUT_ID &&
                    workout.name == StartupRestoreBackupFixture.WORKOUT_NAME
            }
        )

        driver.launchAppFromHome()
        driver.dismissStartupPermissionDialogs(timeoutMs = RESTORE_TIMEOUT_MS)

        val restoredWorkout = waitForRestoredWorkout(context)
        assertEquals(StartupRestoreBackupFixture.WORKOUT_NAME, restoredWorkout.name)
        assertEquals(StartupRestoreBackupFixture.WORKOUT_GLOBAL_ID, restoredWorkout.globalId)

        val exercise = restoredWorkout.workoutComponents.singleOrNull() as? Exercise
            ?: error("Expected restored workout to contain one exercise.")
        assertEquals(StartupRestoreBackupFixture.EXERCISE_ID, exercise.id)
        assertEquals(StartupRestoreBackupFixture.EXERCISE_NAME, exercise.name)

        val set = exercise.sets.singleOrNull() as? WeightSet
            ?: error("Expected restored exercise to contain one weight set.")
        assertEquals(StartupRestoreBackupFixture.SET_ID, set.id)
        assertEquals(7, set.reps)
        assertEquals(42.5, set.weight, 0.001)
    }

    private suspend fun waitForRestoredWorkout(context: Context): com.gabstra.myworkoutassistant.shared.Workout {
        val repository = WorkoutStoreRepository(context.filesDir)
        val deadline = System.currentTimeMillis() + RESTORE_TIMEOUT_MS

        while (System.currentTimeMillis() < deadline) {
            repository.getWorkoutStore().workouts
                .firstOrNull { workout ->
                    workout.id == StartupRestoreBackupFixture.WORKOUT_ID &&
                        workout.name == StartupRestoreBackupFixture.WORKOUT_NAME
                }
                ?.let { return it }

            delay(POLL_INTERVAL_MS)
        }

        error(
            "Timed out waiting for startup restore from Downloads backup. " +
                "Current workouts=${repository.getWorkoutStore().workouts.map { it.name }}"
        )
    }
}
