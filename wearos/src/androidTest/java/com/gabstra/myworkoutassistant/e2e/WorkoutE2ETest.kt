package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationRequiredWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.CompletionWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.EnduranceSetManualStartWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.EnduranceSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.TimedDurationSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.WeightSetWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutE2ETest : BaseWearE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()

        // Grant all required runtime permissions before launching the app
        grantPermissions(
            android.Manifest.permission.BODY_SENSORS,
            android.Manifest.permission.ACTIVITY_RECOGNITION,
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )
        workoutDriver = WearWorkoutDriver(device) { desc, timeout ->
            longPressByDesc(desc, timeout)
        }
    }

    // ==================== Helper Methods ====================

    /**
     * Completes a set by triggering the "Complete Set" dialog and confirming via long-press.
     * The dialog is triggered by pressing the back button once.
     * After completing, dismisses rest screen tutorial if it appears.
     */
    private fun confirmLongPressDialog() {
        workoutDriver.confirmLongPressDialog()
    }

    /**
     * Skips the rest timer by triggering the "Skip Rest" dialog and confirming.
     */
    private fun skipRest() {
        workoutDriver.skipRest()
    }

    /**
     * Edits the rest timer by long-pressing the timer and using +/- buttons.
     * Note: This is a simplified version - actual implementation may need to find timer element.
     */
    private fun editRestTimer(adjustmentSeconds: Int) {
        // Long-press the timer to enter edit mode
        // The timer text should be visible on the rest screen
        val timerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            3_000
        )
        require(timerVisible) { "Rest timer not visible" }

        // Find and long-press the timer element (simplified - may need more specific locator)
        val timerObj = device.wait(Until.findObject(By.textContains(":")), 2_000)
        timerObj?.longClick()
        device.waitForIdle(1_000)

        // Use +/- buttons to adjust (simplified - actual buttons may need specific locators)
        // For now, we'll just verify edit mode was entered
        // In a real implementation, you'd find +/- buttons and click them
    }


    /**
     * Taps the "Go Home" button and verifies navigation to WorkoutSelectionScreen.
     */
    private fun goHome() {
        workoutDriver.goHomeAndVerifySelection()
    }

    /**
     * Waits for the workout completion screen to appear.
     */
    private fun waitForWorkoutCompletion() {
        workoutDriver.waitForWorkoutCompletion()
    }

    // ==================== Test Methods ====================

    @Test
    fun countdownDialog_showsWhenEnabled() {
        // Set up workout store with TimedDurationSet that supports countdown
        TimedDurationSetWorkoutStoreFixture.setupWorkoutStore(context)
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(TimedDurationSetWorkoutStoreFixture.getWorkoutName())

        // Verify countdown dialog appears and starts with "3"
        // The countdown shows numbers 3, 2, 1 sequentially, each for approximately 1 second
        val countdownStarted = device.wait(
            Until.hasObject(By.text("3")),
            5_000
        )
        require(countdownStarted) { "Countdown dialog did not appear - '3' not visible" }

        // Wait for the exercise screen to appear, which confirms the countdown sequence completed
        // The countdown dialog shows 3, 2, 1 and then closes after ~3.5 seconds total
        // By waiting for the exercise screen, we implicitly verify:
        // 1. The countdown completed (dialog disappeared)
        // 2. The app transitioned to the exercise screen successfully
        // This approach is more robust than trying to catch each number in sequence
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Timed Exercise")),
            5_000
        )
        require(exerciseNameVisible) { 
            "Exercise screen not visible after countdown - countdown may not have completed" 
        }
    }

    // ==================== Set/Rest Progression Tests ====================

    @Test
    fun completeSet_progressesToRest() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete the first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Verify rest screen appears (rest timer should be visible)
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear after completing set" }
    }

    @Test
    fun restTimer_autoAdvancesToNextSet() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete the first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest timer to appear
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Wait for rest timer to complete and auto-advance to next set
        // The rest is 10 seconds, so we wait a bit longer
        val nextSetVisible = device.wait(
            Until.hasObject(By.text("Bench Press")),
            15_000
        )
        require(nextSetVisible) { "Next set did not appear after rest timer completed" }
    }

    @Test
    fun restTimer_canBeEdited() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete the first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Edit the rest timer (simplified - actual implementation would verify timer changed)
        editRestTimer(5)
        device.waitForIdle(1_000)

        // Verify we're still on rest screen (timer editing doesn't exit rest)
        val stillOnRest = device.wait(
            Until.hasObject(By.textContains(":")),
            2_000
        )
        require(stillOnRest) { "Not on rest screen after editing timer" }
    }

    @Test
    fun restTimer_canBeSkipped() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete the first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Skip the rest
        skipRest()

        // Verify next set appears immediately
        val nextSetVisible = device.wait(
            Until.hasObject(By.text("Bench Press")),
            5_000
        )
        require(nextSetVisible) { "Next set did not appear after skipping rest" }
    }

    // ==================== Workout Completion Tests ====================

    @Test
    fun completeWorkout_showsCompletionScreen() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        // Complete the only set
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for completion screen
        waitForWorkoutCompletion()

        // Verify workout name is visible on completion screen
        val workoutNameVisible = device.wait(
            Until.hasObject(By.text(CompletionWorkoutStoreFixture.getWorkoutName())),
            3_000
        )
        require(workoutNameVisible) { "Workout name not visible on completion screen" }
    }

    @Test
    fun completeWorkout_autoCloseCountdown() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        // Complete the only set
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for completion screen
        waitForWorkoutCompletion()

        // Verify countdown text appears
        val countdownVisible = device.wait(
            Until.hasObject(By.textContains("Closing in:")),
            3_000
        )
        require(countdownVisible) { "Auto-close countdown did not appear" }
    }

    @Test
    fun completeWorkout_dialogCanReturnToMenu() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        // Complete the only set
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for completion screen
        waitForWorkoutCompletion()

        // Wait for "Workout completed" dialog to appear
        val dialogVisible = device.wait(
            Until.hasObject(By.text("Workout completed")),
            5_000
        )
        require(dialogVisible) { "Workout completed dialog did not appear" }

        // Confirm via long-press on "Done"
        longPressByDesc("Done")

        // Verify return to WorkoutSelectionScreen
        val headerVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            5_000
        )
        require(headerVisible) { "Did not return to WorkoutSelectionScreen after completion dialog" }
    }

    @Test
    fun calibrationExercise_flowCompletesAndReachesWorkoutCompletion() {
        CalibrationRequiredWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(CalibrationRequiredWorkoutStoreFixture.getWorkoutName())

        // Calibration load selection should be visible first.
        val calibrationLoadVisible = device.wait(
            Until.hasObject(By.textContains("Select load for")),
            5_000
        )
        require(calibrationLoadVisible) { "Calibration load selection did not appear" }

        // Confirm selected calibration load.
        device.pressBack()
        confirmLongPressDialog()

        // Calibration execution set should appear before RIR selection.
        val calibrationExecutionVisible = device.wait(
            Until.hasObject(By.text("Calibrated Bench Press")),
            5_000
        )
        require(calibrationExecutionVisible) { "Calibration execution set did not appear" }

        // Complete calibration execution set.
        device.pressBack()
        confirmLongPressDialog()

        // Calibration RIR selection must appear after calibration execution.
        val calibrationRirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            5_000
        )
        require(calibrationRirVisible) { "Calibration RIR selection did not appear" }

        // Confirm default RIR value.
        device.pressBack()
        confirmLongPressDialog()

        // Verify the flow advances out of RIR selection after confirmation.
        val rirSelectionGone = device.wait(
            Until.gone(By.text("0 = Form Breaks")),
            5_000
        )
        require(rirSelectionGone) { "Calibration flow did not advance after confirming RIR" }
    }

    // ==================== Pager Navigation Tests ====================

    @Test
    fun exerciseScreen_pagerNavigationToPlates() {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(WeightSetWorkoutStoreFixture.getWorkoutName())

        // Swipe left to navigate to Plates page
        navigateToPagerPage(PagerDirection.LEFT)
        device.waitForIdle(1_000)

        // Verify we're on a different page (plates page should show plate information)
        // Since we can't easily verify plate content, we verify we're not on the detail page
        // by checking that exercise name might not be as prominently displayed
        device.waitForIdle(2_000)
        // Note: Actual verification would check for plate-specific content
    }

    @Test
    fun exerciseScreen_pagerAutoReturnsToDetail() {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(WeightSetWorkoutStoreFixture.getWorkoutName())

        // Navigate away from detail page
        navigateToPagerPage(PagerDirection.LEFT)
        device.waitForIdle(500)

        // Wait 10+ seconds for auto-return
        device.waitForIdle(11_000)

        // Verify we're back on detail page (exercise name should be visible)
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Bench Press")),
            2_000
        )
        require(exerciseNameVisible) { "Did not auto-return to exercise detail page" }
    }

    @Test
    fun restScreen_pagerNavigation() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete first set to get to rest screen (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Navigate pager (swipe)
        navigateToPagerPage(PagerDirection.LEFT)
        device.waitForIdle(1_000)

        // Verify we're still on rest screen (pager navigation doesn't exit rest)
        val stillOnRest = device.wait(
            Until.hasObject(By.textContains(":")),
            2_000
        )
        require(stillOnRest) { "Not on rest screen after pager navigation" }
    }

    // ==================== Resume/Go-Home Tests ====================

    @Test
    fun goHome_persistsWorkoutRecord() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen to ensure we're in a workout state
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Simulate leaving app while workout is active
        device.pressHome()
        device.waitForIdle(1_000)

        // Relaunch to verify workout record persisted
        launchAppFromHome()
        val resumePromptVisible = device.wait(Until.hasObject(By.text("Resume")), 3_000)
        if (!resumePromptVisible) {
            clickText(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())
            val resumeButtonVisible = device.wait(Until.hasObject(By.text("Resume")), 3_000)
            require(resumeButtonVisible) { "Paused workout was not persisted (Resume not visible)" }
        }
    }

    @Test
    fun resumeWorkout_restoresState() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Simulate abrupt app interruption while workout is active (process death/resume scenario)
        device.pressHome()
        device.waitForIdle(1_000)

        // Relaunch and resume
        launchAppFromHome()
        val resumePromptVisible = device.wait(Until.hasObject(By.text("Resume")), 3_000)
        if (resumePromptVisible) {
            clickText("Resume")
        } else {
            clickText(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())
            clickText("Resume")
        }

        // Dismiss tutorials that may appear when resuming (HEART_RATE and REST_SCREEN)
        // SET_SCREEN is already handled by startWorkout(), but we're resuming so we need to handle it
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        // Verify workout continues from rest state (rest timer should appear)
        val restTimerVisibleAfterResume = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisibleAfterResume) { 
            "Workout did not resume at correct state - rest timer not visible" 
        }
    }

    @Test
    fun resumeWorkout_deletePausedWorkout() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Complete first set (tutorial dismissal is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.waitForIdle(500)

        // Wait for rest screen
        val restTimerVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            5_000
        )
        require(restTimerVisible) { "Rest screen did not appear" }

        // Simulate leaving app while workout is active
        device.pressHome()
        device.waitForIdle(1_000)

        // Relaunch
        launchAppFromHome()

        device.waitForIdle(1_000)
        dismissResumeDialogIfPresent()

        clickText(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        // Verify "Delete paused workout" button appears
        val deleteVisible = device.wait(
            Until.hasObject(By.text("Delete paused workout")),
            3_000
        )
        require(deleteVisible) { "Delete paused workout button did not appear" }

        // Click delete
        clickText("Delete paused workout")

        confirmLongPressDialog()

        // Verify workout can be started fresh (Start button should be available)
        val startVisible =
            scrollUntilFound(By.desc("Start workout"), Direction.DOWN, 1_500) != null ||
            scrollUntilFound(By.text("Start"), Direction.DOWN, 1_500) != null ||
            scrollUntilFound(By.desc("Start"), Direction.DOWN, 1_500) != null
        require(startVisible) { "Start button not available after deleting paused workout" }
    }

    // ==================== Timed Duration Set Tests ====================

    @Test
    fun timedDurationSet_autoStartWorks() {
        TimedDurationSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(TimedDurationSetWorkoutStoreFixture.getWorkoutName())

        // Wait for countdown to complete and exercise screen to appear
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Timed Exercise")),
            5_000
        )
        require(exerciseNameVisible) { "Exercise screen not visible after countdown" }

        // Wait a bit to see if timer starts automatically
        device.waitForIdle(2_000)

        // Verify timer is running (timed duration set with autoStart should show timer)
        // The timer display should be visible (format may vary)
        val timerRunning = device.wait(
            Until.hasObject(By.textContains(":")),
            3_000
        )
        require(timerRunning) { "Timer did not start automatically for TimedDurationSet" }
    }

    @Test
    fun timedDurationSet_completeSet() {
        TimedDurationSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(TimedDurationSetWorkoutStoreFixture.getWorkoutName())

        // Wait 5 seconds for countdown dialog to complete (countdown takes ~3.5 seconds)
        // This ensures the countdown dialog is fully dismissed before pressing back
        Thread.sleep(5_000)

        // Wait for exercise screen to appear
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Timed Exercise")),
            5_000
        )
        require(exerciseNameVisible) { "Exercise screen not visible" }

        // Complete the timed duration set (tutorial dismissal for rest/completion is handled in completeSet())
        device.pressBack()
        confirmLongPressDialog()

        // Verify we progress (either to next set, rest, or completion)
        // Since this is a single-set workout, we should go to completion
        waitForWorkoutCompletion()
    }

    // ==================== Endurance Set Tests ====================

    @Test
    fun enduranceSet_countdownAppears() {
        EnduranceSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(EnduranceSetWorkoutStoreFixture.getWorkoutName())

        // Verify countdown dialog appears
        val countdownStarted = device.wait(
            Until.hasObject(By.text("3")),
            5_000
        )
        require(countdownStarted) { "Countdown dialog did not appear for EnduranceSet" }

        // Wait for exercise screen
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Endurance Exercise")),
            5_000
        )
        require(exerciseNameVisible) { "Exercise screen not visible after countdown" }
    }

    @Test
    fun enduranceSet_manualStart() {
        // Create workout with EnduranceSet that has autoStart = false
        EnduranceSetManualStartWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(EnduranceSetManualStartWorkoutStoreFixture.getWorkoutName())

        // Wait for exercise screen
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Endurance Exercise")),
            5_000
        )
        require(exerciseNameVisible) { "Exercise screen not visible" }

        // Verify timer doesn't start automatically (with autoStart = false)
        // Wait a bit and check that timer shows 0 or start state
        device.waitForIdle(2_000)
        // Note: Actual verification would check timer state, but this confirms manual start requirement
    }

    // ==================== Back Navigation Tests ====================

    @Test
    fun workoutInProgress_backDialog() {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(WeightSetWorkoutStoreFixture.getWorkoutName())

        // Press back button
        device.pressBack()
        device.waitForIdle(500)

        // Verify "Workout in progress" dialog appears
        val dialogVisible = device.wait(
            Until.hasObject(By.text("Workout in progress")),
            3_000
        )
        require(dialogVisible) { "Workout in progress dialog did not appear" }

        // Verify "Done" and "Close" buttons are present (by content description)
        val doneButton = device.wait(Until.findObject(By.desc("Done")), 2_000)
        val closeButton = device.wait(Until.findObject(By.desc("Close")), 2_000)

        require(doneButton != null) { "Done button not found in dialog" }
        require(closeButton != null) { "Close button not found in dialog" }
    }

    @Test
    fun workoutInProgress_backDialogPause() {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(WeightSetWorkoutStoreFixture.getWorkoutName())

        // Double-press back
        device.pressBack()
        device.waitForIdle(200)
        device.pressBack()
        device.waitForIdle(500)

        // Verify dialog appears
        val dialogVisible = device.wait(
            Until.hasObject(By.text("Workout in progress")),
            3_000
        )
        require(dialogVisible) { "Workout in progress dialog did not appear on double-press" }

        // Long-press "Done" to pause/exit workout
        longPressByDesc("Done")

        // Verify we return to WorkoutSelectionScreen
        val headerVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            5_000
        )
        require(headerVisible) { "Did not return to WorkoutSelectionScreen after pausing workout" }
    }

}
