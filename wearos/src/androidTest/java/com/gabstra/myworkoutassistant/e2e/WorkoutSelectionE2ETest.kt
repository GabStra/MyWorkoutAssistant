package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutSelectionE2ETest : BaseWearE2ETest() {

    @Test
    fun launch_showsHeaderAndWorkouts() {
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Header 'My Workout Assistant' not visible on selection screen" }

        val workoutName = "Test Workout"
        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Expected workout '$workoutName' not visible on selection screen" }
    }

    @Test
    fun tapWorkout_navigatesToDetail() {
        val workoutName = "Test Workout"
        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailHeaderAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(detailHeaderAppeared) { "Workout detail screen with name '$workoutName' not visible" }

        val startAppeared = device.wait(Until.hasObject(By.text("Start")), defaultTimeoutMs)
        require(startAppeared) { "Start button not visible on WorkoutDetailScreen" }
    }

    @Test
    fun backFromSelection_exitsApp() {
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Header not visible before back press" }

        device.pressBack()

        val stillVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), 2_000)
        require(!stillVisible) { "App UI still visible after back from selection; expected exit" }
    }
}


