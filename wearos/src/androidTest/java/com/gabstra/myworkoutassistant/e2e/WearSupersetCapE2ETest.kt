package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.SupersetCapWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearSupersetCapE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        SupersetCapWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun supersetTimeCap_autoAdvancesPastBlockHandsFree_toCompletion() = runBlocking {
        startWorkout(SupersetCapWorkoutStoreFixture.getWorkoutName())

        // Enter the capped superset by completing the only set of the first exercise.
        val setCompleted = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = 20_000
        )
        require(setCompleted) { "Failed to complete the pre-superset set" }

        // No further input: the 5s cap must cut past both members and finish the workout.
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
    }
}
