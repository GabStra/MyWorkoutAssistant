package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiSelector
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SmokeE2ETest {

    private fun launchAppFromHome(): Pair<UiDevice, Context> {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val device = UiDevice.getInstance(instrumentation)
        val context: Context = ApplicationProvider.getApplicationContext()

        // Go to the watch home screen
        device.pressHome()

        // Launch the app by package name
        val pkg = context.packageName
        val launchIntent = context.packageManager.getLaunchIntentForPackage(pkg)
            ?: error("Launch intent for package $pkg not found")

        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(launchIntent)

        // Wait for any window from our package to appear
        val appeared = device.wait(Until.hasObject(By.pkg(pkg).depth(0)), 5_000)
        require(appeared) { "Timed out waiting for app ($pkg) to appear on screen" }

        return device to context
    }

    @Test
    fun launchApp_fromHome() {
        val (device, context) = launchAppFromHome()

        // Example assertion: any root view from our package exists
        val root = device.findObject(UiSelector().packageName(context.packageName))
        require(root.exists()) { "App did not launch correctly: no UI from ${context.packageName} found" }
    }

    @Test
    fun launchApp_showsWorkoutSelectionHeader() {
        val (device, _) = launchAppFromHome()

        // The WorkoutSelectionScreen shows a header with the app title text.
        val headerText = "My Workout Assistant"
        val appeared = device.wait(Until.hasObject(By.text(headerText)), 5_000)
        require(appeared) { "Expected header text '$headerText' was not visible after app launch" }
    }

    @Test
    fun launchApp_waitForIdle_stillOnApp() {
        val (device, context) = launchAppFromHome()

        // Let the UI settle and ensure our app is still in the foreground.
        device.waitForIdle(5_000)

        val root = device.findObject(UiSelector().packageName(context.packageName))
        require(root.exists()) { "After waiting for idle, app UI from ${context.packageName} is no longer visible" }
    }
}


