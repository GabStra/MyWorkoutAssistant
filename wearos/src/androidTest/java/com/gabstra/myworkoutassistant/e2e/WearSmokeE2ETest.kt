package com.gabstra.myworkoutassistant.e2e

import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationWorkoutStoreFixture
import org.junit.Test

class WearSmokeE2ETest : WearBaseE2ETest() {

    @Test
    fun appLaunches_toWorkoutSelectionScreen() {
        val headerVisible = createWorkoutDriver().waitForText("My Workout Assistant", defaultTimeoutMs)
        require(headerVisible) { "Workout selection header not visible after app launch" }
    }

    @Test
    fun autoRegulation_noCalibrationScreenOnStart() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        val calibrationLoadAppeared = device.wait(
            Until.hasObject(By.textContains("Select load for")),
            3_000L
        )
        require(!calibrationLoadAppeared) {
            "Auto-regulation workout must not show calibration load screen on start"
        }
        val firstSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(firstSetVisible) {
            "First set screen (exercise name) did not appear; expected no calibration flow"
        }
    }
}

