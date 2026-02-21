package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
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
        val resumed = workoutDriver.resumeOrEnterRecoveredWorkout(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains(":"),
            timeoutMs = defaultTimeoutMs
        )
        require(resumed) { "Could not return to recovered rest state after relaunch" }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restTimerVisibleAfterResume = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restTimerVisibleAfterResume) {
            "Workout did not resume at correct state - rest timer not visible"
        }
    }

    @Test
    fun resumeWorkout_withRestartTimer_showsFullDurationAndCountsDown() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        assertRestTimerVisible()

        workoutDriver.killAppProcessTimed(
            packageName = context.packageName,
            settleMs = 0
        )
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains(":"),
            timeoutMs = 15_000,
            useRestartTimer = true
        )
        require(resumed.enteredWorkout) {
            "Could not return to rest screen after relaunch with Restart timer choice"
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            5_000
        )
        require(restVisible) { "Rest screen not visible after recovery with Restart timer" }

        val initialSeconds = readRestTimerSecondsFromScreen()
        require(initialSeconds != null && initialSeconds >= 55) {
            "After Restart timer choice, rest should show full duration (≥55s). actual=$initialSeconds"
        }

        Thread.sleep(3_000)
        val laterSeconds = readRestTimerSecondsFromScreen()
        require(laterSeconds != null && laterSeconds < initialSeconds) {
            "Rest timer should count down. initial=$initialSeconds later=$laterSeconds"
        }
    }

    private fun readRestTimerSecondsFromScreen(): Int? {
        val root = device.findObject(By.descContains(SetValueSemantics.RestSetTypeDescription)) ?: return null
        val timerText = findRestTimerText(root) ?: return null
        val parts = timerText.split(":")
        if (parts.size != 2) return null
        val minutes = parts[0].toIntOrNull() ?: return null
        val seconds = parts[1].toIntOrNull() ?: return null
        return (minutes * 60) + seconds
    }

    private fun findRestTimerText(root: UiObject2): String? {
        val queue = ArrayDeque<UiObject2>()
        queue.add(root)
        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            val text = runCatching { current.text }.getOrNull()
            if (!text.isNullOrBlank() && text.matches(Regex("\\d{1,2}:\\d{2}"))) return text
            runCatching { current.children }.getOrElse { emptyList() }.forEach { queue.addLast(it) }
        }
        return null
    }

    @Test
    fun timedDurationSet_processDeathRecovery_restoresRunningTimer() {
        TimedDurationSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(TimedDurationSetWorkoutStoreFixture.getWorkoutName())

        val exerciseVisible = device.wait(Until.hasObject(By.text("Timed Exercise")), 5_000)
        require(exerciseVisible) { "Timed exercise screen did not appear" }

        val initialSeconds = workoutDriver.readTimedDurationSeconds()
        val progressDeadline = System.currentTimeMillis() + 15_000
        var preKillSeconds = initialSeconds
        while (System.currentTimeMillis() < progressDeadline) {
            Thread.sleep(1_000)
            preKillSeconds = workoutDriver.readTimedDurationSeconds()
            if (preKillSeconds <= initialSeconds - 1) break
        }
        require(preKillSeconds <= initialSeconds - 1) {
            "Timer did not progress before process death. initial=$initialSeconds, preKill=$preKillSeconds"
        }

        val preKillRead = workoutDriver.readTimedDurationSecondsTimed(
            perAttemptTimeoutMs = 300,
            attempts = 2,
            idleBetweenAttempts = false,
            requireTimerSemantics = true
        )
        preKillSeconds = preKillRead.seconds

        workoutDriver.killAppProcessTimed(
            packageName = context.packageName,
            settleMs = 0
        )
        launchAppFromHome()

        val recoveryResult = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = TimedDurationSetWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.text("Stop"),
            timeoutMs = 15_000
        )
        require(recoveryResult.enteredWorkout) {
            "Recovery UI not available after process death and timed exercise was not restored."
        }

        val timerVisibleAfterResume = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.TimedDurationValueDescription)),
            2_000
        )
        require(timerVisibleAfterResume) { "Timed duration control not visible after resume" }
        val resumedRead = workoutDriver.readTimedDurationSecondsTimed(
            perAttemptTimeoutMs = 300,
            attempts = 2,
            idleBetweenAttempts = false,
            requireTimerSemantics = true
        )
        val resumedSeconds = resumedRead.seconds

        val referenceMs = recoveryResult.enteredWorkoutAtMs
            ?: recoveryResult.resumeActionAtMs
            ?: resumedRead.readAtMs
        val harnessReadDelayMs = resumedRead.readAtMs - referenceMs
        require(harnessReadDelayMs <= 1_500L) {
            "Harness read timer too late after recovery transition. delayMs=$harnessReadDelayMs"
        }
        val strictToleranceSeconds = 2
        require(kotlin.math.abs(resumedSeconds - preKillSeconds) <= strictToleranceSeconds) {
            "Recovered timer is not preserved. expected≈$preKillSeconds (±$strictToleranceSeconds), actual=$resumedSeconds, harnessDelayMs=$harnessReadDelayMs"
        }
        require(resumedSeconds > 0) {
            "Recovered timer resumed at an invalid value. resumed=$resumedSeconds"
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
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

