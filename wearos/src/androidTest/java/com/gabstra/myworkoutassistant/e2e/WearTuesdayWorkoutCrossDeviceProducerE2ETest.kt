package com.gabstra.myworkoutassistant.e2e

import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearTuesdayWorkoutCrossDeviceProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper
    private lateinit var activeViewModel: AppViewModel

    override fun shouldClearPersistedE2eState(): Boolean = false

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun completeTuesdayWorkoutFromSyncedBackup_syncsCompleteHistoryToPhone() {
        startTuesdayWorkoutFromSyncedStore()
        flowHelper.completeWorkoutWithCalibrationEndToEnd(
            expectedCalibrationCount = 2,
            expectedCompletedSetCount = 22,
            activeViewModel = activeViewModel
        )
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private fun startTuesdayWorkoutFromSyncedStore() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: error("Wear activity is not resumed.")
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            activeViewModel = viewModel
            viewModel.setSelectedWorkoutId(WORKOUT_ID)
        }
        val selectionDeadline = System.currentTimeMillis() + 15_000
        while (
            activeViewModel.isCheckingWorkoutRecord.value &&
            System.currentTimeMillis() < selectionDeadline
        ) {
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        require(!activeViewModel.isCheckingWorkoutRecord.value) {
            "Timed out waiting for the Tuesday workout record check."
        }
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            activeViewModel.startWorkout()
            context.getSharedPreferences("workout_state", android.content.Context.MODE_PRIVATE)
                .edit()
                .putBoolean("isWorkoutInProgress", true)
                .commit()
            activeViewModel.consumeStartWorkout()
        }
        val preparationDeadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < preparationDeadline) {
            val preparing = activeViewModel.workoutState.value as? com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState.Preparing
            if (preparing?.dataLoaded == true && !activeViewModel.isSessionHydrationInFlight()) {
                break
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        val preparedState = activeViewModel.workoutState.value as? com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState.Preparing
        require(preparedState?.dataLoaded == true && !activeViewModel.isSessionHydrationInFlight()) {
            "Tuesday workout did not finish preparing."
        }
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            activeViewModel.setWorkoutStart()
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    companion object {
        const val WORKOUT_NAME = "Day 1 - Tuesday Upper Strength + Traps"
        val WORKOUT_ID = java.util.UUID.fromString("4b3a063e-29ef-45e1-99fb-aa38a396c772")
    }
}
