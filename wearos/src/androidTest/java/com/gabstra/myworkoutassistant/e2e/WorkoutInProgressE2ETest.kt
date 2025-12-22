package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutInProgressE2ETest : BaseWearE2ETest() {

    private val workoutName = "Test Workout"

    private fun startWorkoutFromDetail() {
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Selection header not visible" }

        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(detailAppeared) { "Workout detail with '$workoutName' not visible" }

        clickText("Start")
        drainPermissionDialogs()
        dismissTutorialIfPresent()
    }

    @Test
    fun enterWorkoutScreen_fromDetail() {
        startWorkoutFromDetail()

        val preparingVisible = device.wait(Until.hasObject(By.text("Preparing")), 10_000)
        require(preparingVisible) { "WorkoutScreen 'Preparing' state not visible after Start" }
    }

    @Test
    fun pauseAndResume_viaBackDialog() {
        startWorkoutFromDetail()

        device.wait(Until.hasObject(By.text("Preparing")), 10_000)

        device.pressBack()

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout in progress")),
            5_000
        )
        require(dialogTitleVisible) {
            "Expected 'Workout in progress' dialog after back press; not found"
        }

        val noButton = device.wait(
            Until.findObject(By.desc("Close")),
            5_000
        )
        require(noButton != null) { "Close (no) icon not found in dialog" }
        noButton.click()

        val stillOnWorkout = device.wait(Until.hasObject(By.text("Preparing")), 5_000)
        require(stillOnWorkout) { "Workout screen not visible after choosing No (resume)" }
    }

    @Test
    fun endWorkout_viaDialog_navigatesOutOfWorkout() {
        startWorkoutFromDetail()

        device.wait(Until.hasObject(By.text("Preparing")), 10_000)

        device.pressBack()

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout in progress")),
            5_000
        )
        require(dialogTitleVisible) { "Workout in progress dialog not visible" }

        val yesButton = device.wait(
            Until.findObject(By.desc("Done")),
            5_000
        )
        require(yesButton != null) { "Done (yes) icon not found in dialog" }
        yesButton.click()

        val selectionHeaderVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            10_000
        )
        require(selectionHeaderVisible) {
            "Did not navigate back to selection after ending workout"
        }
    }

    @Test
    fun backgroundAndForeground_keepsWorkoutStable() {
        startWorkoutFromDetail()

        val preparingVisible = device.wait(Until.hasObject(By.text("Preparing")), 10_000)
        require(preparingVisible) { "WorkoutScreen not visible before backgrounding" }

        device.pressHome()

        launchAppFromHome()

        val stillVisible = device.wait(Until.hasObject(By.text("Preparing")), 10_000)
        require(stillVisible) { "WorkoutScreen not visible after background/foreground cycle" }
    }
}


