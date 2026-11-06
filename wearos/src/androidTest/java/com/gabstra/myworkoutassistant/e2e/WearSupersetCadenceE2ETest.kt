package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.SupersetCadenceWorkoutStoreFixture
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearSupersetCadenceE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        SupersetCadenceWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun supersetRoundCadence_advancesEveryRoundHandsFree_toCompletion() = runBlocking {
        startWorkout(SupersetCadenceWorkoutStoreFixture.getWorkoutName())

        // Zero input: the 5s cadence must walk all three rounds and finish the workout
        // (3 boundaries + margin).
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 60_000)
    }

    @Test
    fun rotatingEmom_advancesOneMemberPerSlot_toCompletion() = runBlocking {
        val startedAt = System.currentTimeMillis()
        startWorkout(SupersetCadenceWorkoutStoreFixture.getRotatingWorkoutName())

        // Two members x three sets = six slots at 5s each. Round-based cadence would
        // finish after three boundaries, so the elapsed floor proves slot rotation.
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 60_000)
        val elapsedMs = System.currentTimeMillis() - startedAt
        assertTrue(
            "Rotating EMOM finished after ${elapsedMs}ms; expected at least six slots",
            elapsedMs >= 25_000
        )
    }
}
