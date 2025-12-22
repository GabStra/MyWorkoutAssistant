package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutDetailE2ETest : BaseWearE2ETest() {

    private val workoutName = "Test Workout"

    private fun openDetailFromSelection() {
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Selection header not visible" }

        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(detailAppeared) { "Workout detail with '$workoutName' not visible after tap" }
    }

    @Test
    fun openDetail_showsActions() {
        openDetailFromSelection()

        val startVisible = device.wait(Until.hasObject(By.text("Start")), defaultTimeoutMs)
        require(startVisible) { "Start button not visible on WorkoutDetailScreen" }

        device.wait(Until.hasObject(By.text("Send history")), 1_000)

        device.wait(Until.hasObject(By.text("Back")), 1_000)
    }

    @Test
    fun startWorkout_navigatesToWorkoutScreen() {
        openDetailFromSelection()

        clickText("Start")

        // Dismiss heart rate tutorial if it appears (shown when workout starts, before Set/Rest states)
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        
        // Wait for "Preparing HR Sensor" or "Preparing Polar Sensor" text to appear
        // The screen shows "Preparing HR Sensor" not just "Preparing"
        val preparingVisible = device.wait(
            Until.hasObject(By.textContains("Preparing")),
            10_000
        )
        require(preparingVisible) {
            "Expected 'Preparing HR Sensor' or 'Preparing Polar Sensor' text after Start; not found"
        }
    }

    @Test
    fun backFromDetail_returnsToSelection() {
        openDetailFromSelection()

        val backVisible = device.wait(Until.hasObject(By.text("Back")), defaultTimeoutMs)
        require(backVisible) { "Back action not visible on detail" }

        clickText("Back")

        val headerVisible = waitForText("My Workout Assistant")
        require(headerVisible) { "Did not return to WorkoutSelectionScreen after Back" }
    }
}


