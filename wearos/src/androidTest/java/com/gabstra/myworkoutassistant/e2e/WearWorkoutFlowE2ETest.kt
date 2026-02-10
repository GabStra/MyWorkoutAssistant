package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationRequiredWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.CompletionWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.EnduranceSetManualStartWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.TimedDurationSetWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearWorkoutFlowE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun completeSet_progressesToRest() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        assertRestTimerVisible()
    }

    @Test
    fun restTimer_canBeSkipped() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        assertRestTimerVisible()

        workoutDriver.skipRest()

        val nextSetVisible = device.wait(Until.hasObject(By.text("Bench Press")), 5_000)
        require(nextSetVisible) { "Next set did not appear after skipping rest" }
    }

    @Test
    fun completeWorkout_showsCompletionScreen() {
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 20_000)

        val workoutNameVisible = device.wait(
            Until.hasObject(By.text(CompletionWorkoutStoreFixture.getWorkoutName())),
            3_000
        )
        require(workoutNameVisible) { "Workout name not visible on completion screen" }
    }

    @Test
    fun calibrationExercise_flowCompletesAndAdvances() {
        CalibrationRequiredWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CalibrationRequiredWorkoutStoreFixture.getWorkoutName())

        val calibrationLoadVisible = device.wait(Until.hasObject(By.textContains("Select load for")), 5_000)
        require(calibrationLoadVisible) { "Calibration load selection did not appear" }

        workoutDriver.completeCurrentSet()

        val calibrationExecutionVisible = device.wait(Until.hasObject(By.text("Calibrated Bench Press")), 5_000)
        require(calibrationExecutionVisible) { "Calibration execution set did not appear" }

        workoutDriver.completeCurrentSet()

        val calibrationRirVisible = device.wait(Until.hasObject(By.text("0 = Form Breaks")), 5_000)
        require(calibrationRirVisible) { "Calibration RIR selection did not appear" }

        workoutDriver.completeCurrentSet()

        val rirSelectionGone = device.wait(Until.gone(By.text("0 = Form Breaks")), 5_000)
        require(rirSelectionGone) { "Calibration flow did not advance after confirming RIR" }
    }

    @Test
    fun resumeWorkout_restoresState() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        assertRestTimerVisible()

        device.pressHome()
        device.waitForIdle(1_000)

        launchAppFromHome()
        val resumePromptVisible = device.wait(Until.hasObject(By.text("Resume")), 3_000)
        if (resumePromptVisible) {
            workoutDriver.clickText("Resume", defaultTimeoutMs)
        } else {
            workoutDriver.clickText(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(), defaultTimeoutMs)
            workoutDriver.clickText("Resume", defaultTimeoutMs)
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restTimerVisibleAfterResume = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restTimerVisibleAfterResume) {
            "Workout did not resume at correct state - rest timer not visible"
        }
    }

    @Test
    fun timedDurationSet_processDeathRecovery_restoresRunningTimer() {
        TimedDurationSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(TimedDurationSetWorkoutStoreFixture.getWorkoutName())

        val exerciseVisible = device.wait(Until.hasObject(By.text("Timed Exercise")), 5_000)
        require(exerciseVisible) { "Timed exercise screen did not appear" }

        val initialSeconds = workoutDriver.readTimedDurationSeconds()
        Thread.sleep(4_000)
        val preKillSeconds = workoutDriver.readTimedDurationSeconds()
        require(preKillSeconds <= initialSeconds - 1) {
            "Timer did not progress before process death. initial=$initialSeconds, preKill=$preKillSeconds"
        }

        workoutDriver.killAppProcess(context.packageName)
        launchAppFromHome()

        val processDeathPromptVisible = device.wait(Until.hasObject(By.text("Workout interrupted")), 5_000)
        if (processDeathPromptVisible) {
            workoutDriver.clickText("Resume", defaultTimeoutMs)
        } else {
            val resumeVisible = device.wait(Until.hasObject(By.text("Resume")), 3_000)
            if (resumeVisible) {
                workoutDriver.clickText("Resume", defaultTimeoutMs)
            } else {
                val alreadyInWorkout = device.wait(Until.hasObject(By.text("Timed Exercise")), 2_000)
                if (!alreadyInWorkout) {
                    workoutDriver.clickText(TimedDurationSetWorkoutStoreFixture.getWorkoutName(), defaultTimeoutMs)
                    val resumeInDetailVisible = device.wait(Until.hasObject(By.textContains("Resume")), 5_000)
                    require(resumeInDetailVisible) {
                        "Recovery UI not available after process death. 'Resume' button not found."
                    }
                    workoutDriver.clickText("Resume", defaultTimeoutMs)
                }
            }
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)

        val exerciseVisibleAfterResume = device.wait(Until.hasObject(By.text("Timed Exercise")), 10_000)
        require(exerciseVisibleAfterResume) { "Timed exercise screen not visible after resume" }

        val resumedSeconds = workoutDriver.readTimedDurationSeconds()
        require(resumedSeconds < preKillSeconds) {
            "Recovered timer was not restored as running. preKill=$preKillSeconds, resumed=$resumedSeconds"
        }
        require(resumedSeconds > 0) {
            "Recovered timer resumed at an invalid value. resumed=$resumedSeconds"
        }
    }

    @Test
    fun enduranceSet_manualStartCompletesWorkout() {
        EnduranceSetManualStartWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(EnduranceSetManualStartWorkoutStoreFixture.getWorkoutName())

        val exerciseNameVisible = device.wait(Until.hasObject(By.text("Endurance Exercise")), 5_000)
        require(exerciseNameVisible) { "Exercise screen not visible" }

        workoutDriver.completeTimedSet(timeoutMs = 10_000)
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 20_000)
    }

    private fun assertRestTimerVisible() {
        val restTimerVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restTimerVisible) { "Rest screen did not appear" }
    }
}

