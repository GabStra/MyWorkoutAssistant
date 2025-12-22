package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TutorialOverlayE2ETest : BaseWearE2ETest() {

    private val workoutName = "Test Workout"

    /**
     * Starts a workout, then verifies that any tutorial overlay
     * (with a "Got it" button at the bottom) can be dismissed using
     * the shared helper and that the underlying workout UI is visible.
     */
    @Test
    fun dismissesTutorialOverlay_ifPresent() {
        // Ensure we are on the workout selection screen.
        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Selection header not visible" }

        // Open the known test workout.
        val workoutAppeared = device.wait(
            Until.hasObject(By.text(workoutName)),
            defaultTimeoutMs
        )
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailAppeared = device.wait(
            Until.hasObject(By.text(workoutName)),
            defaultTimeoutMs
        )
        require(detailAppeared) { "Workout detail with '$workoutName' not visible" }

        // Start the workout.
        clickText("Start")
        drainPermissionDialogs()

        // At this point, a tutorial overlay may or may not appear.
        // Invoke the helper to dismiss it if present.
        dismissTutorialIfPresent()

        // Verify that the tutorial button is no longer present.
        val overlayButtonStillThere = device.hasObject(By.text("Got it"))
        require(!overlayButtonStillThere) { "\"Got it\" button still visible; tutorial overlay was not dismissed" }

        // And that we eventually see the workout screen content (e.g., "Preparing").
        val preparingVisible = device.wait(
            Until.hasObject(By.text("Preparing")),
            defaultTimeoutMs
        )
        require(preparingVisible) { "WorkoutScreen 'Preparing' state not visible after dismissing tutorial overlay" }
    }
}


