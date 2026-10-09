package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Wear phase of the WOD importer e2e: after the phone phase imported the
 * generated WOD package and synced, the workout must have arrived on the watch
 * and be selectable from the workout selection screen.
 *
 * Deliberately does NOT seed a local Wear fixture — seeding would stop this
 * test from proving phone -> Wear delivery (same contract as the other
 * PhoneToWear verification tests).
 */
@RunWith(AndroidJUnit4::class)
class WodWorkoutVisibilityE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    // Overridable via instrumentation (-e expected_workout_name ...) so the same
    // test verifies visibility for any synced plan package.
    private val workoutName =
        androidx.test.platform.app.InstrumentationRegistry.getArguments()
            .getString("expected_workout_name")
            ?: "WOD 2026-10-06 HYROX-PREP"

    override fun prepareAppStateBeforeLaunch() {
        // The phone phase seeds and syncs; nothing to seed locally.
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun syncedWodWorkout_isSelectableOnWear() = runBlocking {
        waitForSyncedWodOnWear()
        val visible = ensureWorkoutSelectionVisible(workoutName)
        require(visible) { "Synced WOD workout '$workoutName' is not visible/selectable on the watch" }
    }

    private suspend fun waitForSyncedWodOnWear() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        var lastCount = 0
        while (System.currentTimeMillis() < deadline) {
            val workouts = WorkoutStoreRepository(context.filesDir).getWorkoutStore().workouts
            lastCount = workouts.size
            if (workouts.any { it.name == workoutName }) {
                return
            }
            delay(2_000)
        }
        error("WOD workout never arrived on the watch within the sync window (last workout count: $lastCount)")
    }
}
