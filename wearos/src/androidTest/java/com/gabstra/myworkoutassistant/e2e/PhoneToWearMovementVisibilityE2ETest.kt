package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.MovementPreviewNavigationHelper
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearMovementVisibilityE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var movementPreviewHelper: MovementPreviewNavigationHelper

    override fun prepareAppStateBeforeLaunch() {
        // The cross-device runner seeds the phone, then waits for that phone state to sync here.
        // Do not seed a local Wear fixture, or this test would stop proving phone -> Wear delivery.
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        movementPreviewHelper = MovementPreviewNavigationHelper(device, workoutDriver)
    }

    @Test
    fun phoneLoadedMovement_syncsToWearAndRendersInWorkoutFlow() = runBlocking {
        waitForSyncedPhoneMovementOnWear()

        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())

        movementPreviewHelper.requireMovementPreviewVisibleAndStable()
    }

    private suspend fun waitForSyncedPhoneMovementOnWear() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val expectedMovementRef = CrossDeviceSyncWorkoutStoreFixture.movementRef()
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        var failureDetail = "movement sync was not checked"

        while (System.currentTimeMillis() < deadline) {
            val syncedExercise = WorkoutStoreRepository(context.filesDir)
                .getWorkoutStore()
                .workouts
                .asSequence()
                .flatMap { workout ->
                    workout.workoutComponents.asSequence().flatMap { component ->
                        when (component) {
                            is Exercise -> sequenceOf(component)
                            is Superset -> component.exercises.asSequence()
                            else -> emptySequence()
                        }
                    }
                }
                .firstOrNull { exercise -> exercise.id == CrossDeviceSyncWorkoutStoreFixture.EXERCISE_A_ID }

            val movementRef = syncedExercise?.movementRef
            val movementJson = movementRef?.let {
                ExerciseMovementStorage.readMovementJson(context, it)
            }

            when {
                syncedExercise == null -> failureDetail = "exercise A was not found in synced workout store"
                movementRef == null -> failureDetail = "exercise A did not have a movementRef"
                movementRef != expectedMovementRef -> {
                    failureDetail = "movementRef mismatch. expected=$expectedMovementRef actual=$movementRef"
                }
                movementJson == null -> failureDetail = "movement JSON file was not restored or failed hash validation"
                movementJson != CrossDeviceSyncWorkoutStoreFixture.MOVEMENT_JSON.trimIndent() -> {
                    failureDetail = "movement JSON content mismatch"
                }
                else -> return
            }

            delay(500)
        }

        error("Expected phone-loaded exercise movement not found on Wear within timeout: $failureDetail")
    }
}
