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

        val calibrationLoadVisible = device.wait(Until.hasObject(By.textContains("Set load for")), 5_000)
        require(calibrationLoadVisible) { "Calibration load selection did not appear" }

        workoutDriver.completeCurrentSet(timeoutMs = 10_000)
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

        val preKillSeconds = waitForRestTimerAtMost(
            targetSeconds = 45,
            timeoutMs = 25_000
        ) ?: readRestTimerSecondsFromScreen()
        require(preKillSeconds != null && preKillSeconds <= 45) {
            "Rest timer did not decrease enough before kill. preKill=$preKillSeconds"
        }

        workoutDriver.killAppProcessTimed(
            packageName = context.packageName,
            settleMs = 0
        )
        launchAppFromHome()
        val restartOptionVisible = device.wait(
            Until.hasObject(By.desc("Recovery timer restart option")),
            3_000
        ) || device.hasObject(By.textContains("Restart timer"))

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.descContains(SetValueSemantics.RestSetTypeDescription),
            timeoutMs = 25_000,
            useRestartTimer = restartOptionVisible
        )
        require(resumed.enteredWorkout) {
            "Could not return to rest screen after relaunch with Restart timer choice"
        }

        val restVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            5_000
        )
        require(restVisible) { "Rest screen not visible after recovery with Restart timer" }

        val initialReadAtMs = System.currentTimeMillis()
        var initialSeconds = readRestTimerSecondsFromScreen()
        if (initialSeconds == null) {
            dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
            dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
            initialSeconds = readRestTimerSecondsFromScreen()
        }
        require(initialSeconds != null) {
            "Could not read rest timer after restart recovery"
        }
        val recoveryReferenceMs = resumed.enteredWorkoutAtMs ?: resumed.resumeActionAtMs ?: initialReadAtMs
        val elapsedSinceRecoverySeconds =
            ((initialReadAtMs - recoveryReferenceMs).coerceAtLeast(0L) / 1_000L).toInt()
        val expectedRestartSeconds = (60 - elapsedSinceRecoverySeconds).coerceAtLeast(0)
        val minExpectedRestart = (expectedRestartSeconds - 8).coerceAtLeast(0)
        val maxExpectedRestart = (expectedRestartSeconds + 6).coerceAtMost(60)
        if (restartOptionVisible) {
            require(initialSeconds in minExpectedRestart..maxExpectedRestart) {
                "Restart timer should match elapsed-time restart bounds. " +
                    "preKill=$preKillSeconds, elapsedSinceRecovery=$elapsedSinceRecoverySeconds, " +
                    "expectedRange=[$minExpectedRestart..$maxExpectedRestart], actual=$initialSeconds"
            }
        } else {
            require(initialSeconds <= (preKillSeconds + 6)) {
                "Without restart option, resumed timer should be near continued remainder. preKill=$preKillSeconds resumed=$initialSeconds"
            }
        }

        val laterSeconds = waitForRestTimerDecrease(initialSeconds = initialSeconds, timeoutMs = 6_000)
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
            device.waitForIdle(250)
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
            inWorkoutSelector = By.descContains(SetValueSemantics.TimedDurationValueDescription),
            timeoutMs = 25_000
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
        // Timer keeps running across background/kill/relaunch, so compare against an elapsed-time
        // projection from the last pre-kill read instead of a symmetric absolute delta.
        val elapsedSincePreKillSeconds =
            ((resumedRead.readAtMs - preKillRead.readAtMs).coerceAtLeast(0L) / 1_000L).toInt()
        val expectedAfterElapsed = (preKillSeconds - elapsedSincePreKillSeconds).coerceAtLeast(0)
        val earlyReadToleranceSeconds = 3
        val lateRecoveryToleranceSeconds = 8
        val minExpected = (expectedAfterElapsed - lateRecoveryToleranceSeconds).coerceAtLeast(0)
        val maxExpected = (preKillSeconds + earlyReadToleranceSeconds).coerceAtMost(initialSeconds)
        require(resumedSeconds in minExpected..maxExpected) {
            "Recovered timer is outside elapsed-time bounds. " +
                "preKill=$preKillSeconds, elapsedSincePreKill=$elapsedSincePreKillSeconds, " +
                "expectedRange=[$minExpected..$maxExpected], actual=$resumedSeconds, " +
                "harnessDelayMs=$harnessReadDelayMs"
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

    private fun waitForRestTimerDecrease(initialSeconds: Int, timeoutMs: Long): Int? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val current = readRestTimerSecondsFromScreen()
            if (current != null && current < initialSeconds) {
                return current
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return readRestTimerSecondsFromScreen()
    }

    private fun waitForRestTimerAtMost(targetSeconds: Int, timeoutMs: Long): Int? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val current = readRestTimerSecondsFromScreen()
            if (current != null && current <= targetSeconds) {
                return current
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return readRestTimerSecondsFromScreen()
    }
}
