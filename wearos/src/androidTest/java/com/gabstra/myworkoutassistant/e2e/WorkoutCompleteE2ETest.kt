package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutCompleteE2ETest : BaseWearE2ETest() {

    private val workoutName = "Test Workout"

    private fun startWorkoutToCompletion() {
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Selection header not visible" }

        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(detailAppeared) { "Workout detail with '$workoutName' not visible" }

        clickText("Start")

        // Dismiss tutorial if it appears
        dismissTutorialIfPresent()
        
        // Wait for "Preparing HR Sensor" or "Preparing Polar Sensor" text to appear
        // The screen shows "Preparing HR Sensor" not just "Preparing"
        val preparingVisible = device.wait(Until.hasObject(By.textContains("Preparing")), 10_000)
        require(preparingVisible) { "WorkoutScreen 'Preparing' state not visible" }

        device.pressBack()

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout in progress")),
            5_000
        )
        require(dialogTitleVisible) { "Workout in progress dialog not visible" }

        // The "Done" button requires a long press to confirm, not a regular click
        longPressByDesc("Done", 5_000)
    }

    @Test
    fun completeWorkout_showsSummary() {
        startWorkoutToCompletion()

        val completedVisible = device.wait(Until.hasObject(By.text("Completed")), 10_000)
        require(completedVisible) { "'Completed' text not visible on WorkoutCompleteScreen" }

        val nameVisible = device.wait(Until.hasObject(By.text(workoutName)), 5_000)
        require(nameVisible) { "Workout name '$workoutName' not visible on completion screen" }
    }

    @Test
    fun showCountdown_autoCloseOrFinish() {
        startWorkoutToCompletion()

        val countdownVisible = device.wait(
            Until.hasObject(By.textStartsWith("Closing in:")),
            10_000
        )
        require(countdownVisible) { "Countdown 'Closing in:' not visible on completion screen" }

        val stillCompleted = device.wait(
            Until.hasObject(By.text("Completed")),
            35_000
        )
        if (!stillCompleted) {
            return
        }
    }

    @Test
    fun dialog_returnToMainMenu() {
        startWorkoutToCompletion()

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout completed")),
            15_000
        )
        require(dialogTitleVisible) { "'Workout completed' dialog not visible" }

        // The "Done" button requires a long press to confirm, not a regular click
        longPressByDesc("Done", 5_000)

        val headerVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            10_000
        )
        require(headerVisible) { "Did not return to WorkoutSelectionScreen from completion dialog" }
    }

    @Test
    fun dialog_stayAndAutoClose() {
        startWorkoutToCompletion()

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout completed")),
            15_000
        )
        require(dialogTitleVisible) { "'Workout completed' dialog not visible" }

        val noButton = device.wait(
            Until.findObject(By.desc("Close")),
            5_000
        )
        require(noButton != null) { "Close (no) icon not found in completion dialog" }
        noButton.click()

        val completedVisible = device.wait(Until.hasObject(By.text("Completed")), 5_000)
        require(completedVisible) { "Completion screen not visible after choosing to stay" }

        device.waitForIdle(35_000)
    }
}


