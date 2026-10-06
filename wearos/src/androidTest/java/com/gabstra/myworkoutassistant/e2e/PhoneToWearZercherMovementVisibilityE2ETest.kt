package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ZercherMovementWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.MovementPreviewNavigationHelper
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearZercherMovementVisibilityE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var movementPreviewHelper: MovementPreviewNavigationHelper

    override fun prepareAppStateBeforeLaunch() {
        // The phone preparation test owns the workout store and movement payload for this run.
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        movementPreviewHelper = MovementPreviewNavigationHelper(device, workoutDriver)
    }

    @Test
    fun phoneLoadedZercherMovement_syncsToWearAndRendersInWorkoutFlow() = runBlocking {
        waitForSyncedZercherMovementOnWear()

        startWorkout(ZercherMovementWorkoutStoreFixture.WORKOUT_NAME)

        movementPreviewHelper.requireMovementPreviewVisibleAndStable()
    }

    private suspend fun waitForSyncedZercherMovementOnWear() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val testContext = InstrumentationRegistry.getInstrumentation().context
        val expectedMovementJson = ZercherMovementWorkoutStoreFixture.readMovementJson(testContext)
        val expectedMovementRef = ZercherMovementWorkoutStoreFixture.movementRef(expectedMovementJson)
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
                .firstOrNull { exercise -> exercise.id == ZercherMovementWorkoutStoreFixture.EXERCISE_ID }

            val movementRef = syncedExercise?.movementRef
            val movementJson = movementRef?.let {
                ExerciseMovementStorage.readMovementJson(context, it)
            }

            when {
                syncedExercise == null -> failureDetail = "Zercher exercise was not found in synced workout store"
                movementRef == null -> failureDetail = "Zercher exercise did not have a movementRef"
                movementRef != expectedMovementRef -> {
                    failureDetail = "movementRef mismatch. expected=$expectedMovementRef actual=$movementRef"
                }
                movementJson == null -> failureDetail = "movement JSON file was not restored or failed hash validation"
                movementJson != expectedMovementJson -> failureDetail = "movement JSON content mismatch"
                else -> {
                    assertMovementJsonIsCanonicalUpright(movementJson)
                    return
                }
            }

            delay(500)
        }

        error("Expected phone-loaded Zercher movement not found on Wear within timeout: $failureDetail")
    }

    private fun assertMovementJsonIsCanonicalUpright(movementJson: String) {
        val root = JSONObject(movementJson)
        val config = root.getJSONObject("bakedPreviewConfiguration")
        assertTrue(
            "Wear movement JSON must use canonical Y-up coordinates.",
            config.optBoolean("canonicalWorldUp", false)
        )

        val firstFrameJoints = root.getJSONArray("frames")
            .getJSONObject(0)
            .getJSONObject("joints")
        val headY = firstFrameJoints.getJSONArray("head").getDouble(1)
        val pelvisY = firstFrameJoints.getJSONArray("pelvis").getDouble(1)
        val leftFootY = firstFrameJoints.getJSONArray("left_foot").getDouble(1)
        val rightFootY = firstFrameJoints.getJSONArray("right_foot").getDouble(1)

        assertTrue(
            "Wear movement JSON is upside down: expected head above pelvis.",
            headY > pelvisY
        )
        assertTrue(
            "Wear movement JSON is upside down: expected pelvis above feet.",
            pelvisY > leftFootY && pelvisY > rightFootY
        )
    }
}
