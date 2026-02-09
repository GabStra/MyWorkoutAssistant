package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CompletionWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.TimedDurationManualStartWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearWorkoutDriverContractTest : BaseWearE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()

        grantPermissions(
            android.Manifest.permission.BODY_SENSORS,
            android.Manifest.permission.ACTIVITY_RECOGNITION,
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )

        workoutDriver = WearWorkoutDriver(device) { desc, timeout ->
            longPressByDesc(desc, timeout)
        }
    }

    @Test
    fun driver_completeCurrentSet_movesFromSetToRest() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Expected rest timer after completeCurrentSet()" }
    }

    @Test
    fun driver_skipRest_movesBackToSetScreen() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Expected rest timer before skipRest()" }

        workoutDriver.skipRest()

        val setVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            5_000
        )
        require(setVisible) { "Expected set screen after skipRest()" }
    }

    @Test
    fun driver_completeTimedSet_handlesManualStartStopFlow() {
        TimedDurationManualStartWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(TimedDurationManualStartWorkoutStoreFixture.getWorkoutName())

        val timedSetVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)),
            10_000
        )
        require(timedSetVisible) { "Expected timed duration set screen" }

        workoutDriver.completeTimedSet()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 20_000)
    }

    @Test
    fun driver_waitForWorkoutCompletion_detectsCompletedState() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 15_000)
    }

    @Test
    fun driver_goHomeAndVerifySelection_returnsToWorkoutSelection() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 15_000)

        workoutDriver.goHomeAndVerifySelection(timeoutMs = 10_000)
    }
}
