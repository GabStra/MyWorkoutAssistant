package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiSelector
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SmokeE2ETest : BaseWearE2ETest() {

    @Test
    fun launchApp_fromHome() {
        // Example assertion: any root view from our package exists
        val root = device.findObject(UiSelector().packageName(context.packageName))
        require(root.exists()) { "App did not launch correctly: no UI from ${context.packageName} found" }
    }

    @Test
    fun launchApp_showsWorkoutSelectionHeader() {
        // The WorkoutSelectionScreen shows a header with the app title text.
        val headerText = "My Workout Assistant"
        val appeared = device.wait(Until.hasObject(By.text(headerText)), 15_000)
        require(appeared) { "Expected header text '$headerText' was not visible after app launch" }
    }

    @Test
    fun launchApp_waitForIdle_stillOnApp() {
        // Let the UI settle and ensure our app is still in the foreground.
        device.waitForIdle(5_000)

        val root = device.findObject(UiSelector().packageName(context.packageName))
        require(root.exists()) { "After waiting for idle, app UI from ${context.packageName} is no longer visible" }
    }
}


