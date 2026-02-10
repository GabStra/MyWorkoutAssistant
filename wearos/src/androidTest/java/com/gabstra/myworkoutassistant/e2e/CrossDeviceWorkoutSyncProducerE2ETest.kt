package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CrossDeviceWorkoutSyncProducerE2ETest : BaseWearE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper

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

        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun completeWorkout_syncsHistoryToPhone() {
        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
        flowHelper.completeComplexWorkoutWithDeterministicModifications()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    @Test
    fun completeCalibrationWorkout_executesCalibrationFlowInCrossDeviceSession() {
        val workoutName = CrossDeviceSyncWorkoutStoreFixture.getCalibrationWorkoutName()
        startWorkout(workoutName)
        flowHelper.completeCalibrationWorkoutFlow(workoutName) { pausedWorkoutName ->
            resumeCalibrationWorkoutIfPaused(pausedWorkoutName)
        }
    }

    private fun resumeCalibrationWorkoutIfPaused(workoutName: String) {
        val workoutVisible = device.wait(Until.hasObject(By.text(workoutName)), 2_000)
        if (!workoutVisible) return

        runCatching {
            workoutDriver.clickText(workoutName, defaultTimeoutMs)
            workoutDriver.clickText("Resume", defaultTimeoutMs)
            dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
            dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
            dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        }
    }
}
