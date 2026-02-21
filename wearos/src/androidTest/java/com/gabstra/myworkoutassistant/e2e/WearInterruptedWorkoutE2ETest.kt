package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationRequiredWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class WearInterruptedWorkoutE2ETest : WearBaseE2ETest() {

    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    /**
     * Runs first (name order) so no prior test has left unfinished workout histories.
     * Clears workout_state prefs and relaunches; asserts no recovery dialog appears.
     */
    @Test
    fun cleanLaunch_noInterruptedWorkout_doesNotShowRecoveryDialog() {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE).edit().clear().commit()
        device.pressHome()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        launchAppFromHome()

        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), defaultTimeoutMs)
        require(selectionVisible) { "Selection screen (My Workout Assistant) not visible" }

        val noRecoveryDialog = !workoutDriver.waitForRecoveryDialog(3_000)
        require(noRecoveryDialog) {
            "Recovery dialog should not appear when there are no interrupted workouts"
        }
    }

    @Test
    fun recoveryDialog_appearsAfterLeavingWorkoutAndRelaunching() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Rest screen did not appear" }

        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear after leaving workout and relaunching" }

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkout(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains(":"),
            timeoutMs = defaultTimeoutMs
        )
        require(resumed) { "Could not return to rest screen after resume" }
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        val restVisibleAfterResume = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisibleAfterResume) { "Rest screen not visible after resume" }
    }

    @Test
    fun recoveryDialog_discard_clearsWorkoutAndNextLaunchShowsNoDialog() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear" }

        workoutDriver.clickRecoveryDiscard(5_000)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)

        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), 5_000)
        require(selectionVisible) { "Selection screen not visible after discard" }
        require(!workoutDriver.isRecoveryDialogVisible()) { "Recovery dialog should be closed after discard" }

        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)

        val noDialogOnSecondLaunch = !workoutDriver.waitForRecoveryDialog(3_000)
        require(noDialogOnSecondLaunch) {
            "Recovery dialog should not appear after workout was discarded"
        }
    }

    @Test
    fun recoveryDialog_dismiss_closesDialogWorkoutRemainsInterrupted() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear" }

        device.pressBack()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)

        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), 5_000)
        require(selectionVisible) { "Selection screen not visible after dismiss" }
        require(!workoutDriver.isRecoveryDialogVisible()) { "Recovery dialog should be closed after dismiss" }

        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppearsAgain = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppearsAgain) {
            "Recovery dialog should appear again on relaunch (workout still interrupted)"
        }
    }

    @Test
    fun resumeWithContinueTimer_restoresRestTimerValue() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Rest screen did not appear" }

        Thread.sleep(5_000)
        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains(":"),
            timeoutMs = 15_000,
            useRestartTimer = false
        )
        require(resumed.enteredWorkout) {
            "Could not return to rest screen with Continue timer"
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 3_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 3_000)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)

        val restVisibleAfterRecovery = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            8_000
        )
        require(restVisibleAfterRecovery) { "Rest screen not visible after recovery with Continue timer" }

        val seconds = readRestTimerSecondsFromScreen()
        require(seconds != null && seconds < 55) {
            "With Continue timer, rest should show remaining time (< 55s), actual=$seconds"
        }
    }

    @Test
    fun calibrationRecovery_continueCalibration_resumesAtCalibration() {
        CalibrationRequiredWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CalibrationRequiredWorkoutStoreFixture.getWorkoutName())

        val calibrationLoadVisible = device.wait(Until.hasObject(By.textContains("Set load")), 10_000)
        require(calibrationLoadVisible) { "Calibration load selection did not appear" }

        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = CalibrationRequiredWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains("Set load"),
            timeoutMs = 15_000,
            useRestartCalibration = false
        )
        require(resumed.enteredWorkout) {
            "Could not resume into calibration after process death"
        }

        val calibrationOrSetVisible = device.wait(Until.hasObject(By.textContains("Set load")), 5_000) ||
            device.wait(Until.hasObject(By.text("Calibrated Bench Press")), 5_000)
        require(calibrationOrSetVisible) {
            "Calibration or set screen not visible after Continue calibration"
        }
    }

    @Test
    fun calibrationRecovery_restartCalibration_resetsToCalibrationLoad() {
        CalibrationRequiredWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(CalibrationRequiredWorkoutStoreFixture.getWorkoutName())

        val calibrationLoadVisible = device.wait(Until.hasObject(By.textContains("Set load")), 10_000)
        require(calibrationLoadVisible) { "Calibration load selection did not appear" }

        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = CalibrationRequiredWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains("Set load"),
            timeoutMs = 15_000,
            useRestartCalibration = true
        )
        require(resumed.enteredWorkout) {
            "Could not resume with Restart calibration"
        }

        val calibrationLoadVisibleAgain = device.wait(Until.hasObject(By.textContains("Set load")), 8_000)
        require(calibrationLoadVisibleAgain) {
            "Calibration load selection should be visible after Restart calibration"
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
}
