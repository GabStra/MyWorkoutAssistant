package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationRequiredWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.PolarRecoveryWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.util.regex.Pattern

@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class WearIncompleteWorkoutE2ETest : WearBaseE2ETest() {

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
    fun cleanLaunch_noIncompleteWorkout_doesNotShowRecoveryDialog() {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE).edit().clear().commit()
        device.pressHome()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        launchAppFromHome()

        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), defaultTimeoutMs)
        require(selectionVisible) { "Selection screen (My Workout Assistant) not visible" }

        val noRecoveryDialog = !workoutDriver.waitForRecoveryDialog(3_000)
        require(noRecoveryDialog) {
            "Recovery dialog should not appear when there are no incomplete workouts"
        }
    }

    @Test
    fun recoveryDialog_discard_clearsWorkoutAndNextLaunchShowsNoDialog() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        val db = AppDatabase.getDatabase(context)
        val incompleteBefore = runBlocking {
            db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(false).size
        }
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        completeCurrentSetDeterministically()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear" }

        workoutDriver.clickRecoveryDiscard(5_000)
        val workoutStatePrefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val discardDeadline = System.currentTimeMillis() + 8_000
        var dialogClosed = false
        while (System.currentTimeMillis() < discardDeadline) {
            val inProgress = workoutStatePrefs.getBoolean("isWorkoutInProgress", false)
            dialogClosed = device.wait(Until.gone(By.desc("Recovery discard action")), 800) ||
                !workoutDriver.isRecoveryDialogVisible()
            if (!inProgress && dialogClosed) break
            if (workoutDriver.isRecoveryDialogVisible()) {
                workoutDriver.clickRecoveryDiscard(1_500)
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        if (!dialogClosed) {
            // Some emulator runs keep the dialog visible longer even after state clear.
            // Dismiss navigation and verify persistence contract on next launch.
            device.pressBack()
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        if (!device.hasObject(By.text("My Workout Assistant"))) {
            device.pressBack()
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), 10_000)
        require(selectionVisible) { "Selection screen not visible after discard" }

        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)

        val incompleteCount = runBlocking {
            db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(false).size
        }
        require(incompleteCount <= incompleteBefore) {
            "Discard should clear the newly incomplete workout history row. before=$incompleteBefore after=$incompleteCount"
        }
    }

    @Test
    fun recoveryDialog_dismiss_closesDialogWorkoutRemainsIncomplete() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        completeCurrentSetDeterministically()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear" }

        workoutDriver.clickRecoveryDismiss(5_000)
        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)

        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)
        val selectionVisible =
            ensureWorkoutSelectionVisible(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())
        require(selectionVisible) { "Selection screen not visible after dismiss" }
        require(!workoutDriver.isRecoveryDialogVisible()) { "Recovery dialog should be closed after dismiss" }

        launchAppFromHome()

        val dialogAppearsAgain = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppearsAgain) {
            "Recovery dialog should appear again on relaunch (workout still incomplete)"
        }
    }

    @Test
    fun resumeWithContinueTimer_restoresRestTimerValue() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        completeCurrentSetDeterministically()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        val restVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            5_000
        )
        require(restVisible) { "Rest screen did not appear" }

        val initialSeconds = readRestTimerSecondsFromScreen()
        val preKillSeconds = if (initialSeconds != null) {
            waitForRestTimerDecrease(initialSeconds = initialSeconds, timeoutMs = 6_000) ?: initialSeconds
        } else {
            null
        }
        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        launchAppFromHome()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.descContains(SetValueSemantics.RestSetTypeDescription),
            timeoutMs = 20_000,
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

        val resumedSeconds = readRestTimerSecondsFromScreen()
        require(resumedSeconds != null) { "Could not read resumed rest timer value" }
        require(preKillSeconds != null) { "Could not read pre-kill rest timer value" }
        require(resumedSeconds <= (preKillSeconds + 4)) {
            "With Continue timer, resumed timer should be near pre-kill remaining time. preKill=$preKillSeconds resumed=$resumedSeconds"
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

        workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = CalibrationRequiredWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.textContains("Set load"),
            timeoutMs = 25_000,
            useRestartCalibration = true
        )
        val calibrationLoadVisibleAgain = device.wait(Until.hasObject(By.textContains("Set load")), 15_000)
        val calibrationExerciseVisible = device.wait(Until.hasObject(By.text("Calibrated Bench Press")), 3_000)
        require(calibrationLoadVisibleAgain || calibrationExerciseVisible) {
            "Restart calibration should return to calibration flow (load selection or first calibration exercise)"
        }
    }

    @Test
    fun recoveryDialog_resumeForPolarWorkout_reconnectsExternalPrepAndSkipResumesWorkout() {
        PolarRecoveryWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(PolarRecoveryWorkoutStoreFixture.getWorkoutName())

        require(waitForPolarPreparingScreen(10_000)) {
            "Polar preparation screen did not appear after starting workout"
        }
        require(waitForExternalSkipButton(40_000)) {
            "Skip button did not appear on Polar preparation screen"
        }

        workoutDriver.clickText("Skip", 5_000)
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 3_000)

        val setVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            10_000
        )
        require(setVisible) { "Workout set screen did not appear after skipping Polar connection" }

        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        launchAppFromHome()

        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) { "Recovery dialog did not appear after process death" }

        val recoveryResumeClicked = workoutDriver.clickRecoveryResume(timeoutMs = 8_000)
        require(recoveryResumeClicked) { "Could not click Resume in the recovery dialog" }

        require(waitForPolarPreparingScreen(10_000)) {
            "Recovery resume should return to Polar preparation instead of generic heart-rate preparation. Visible UI: ${describeVisibleUi()}"
        }
        require(!device.hasObject(By.text("Getting heart rate ready"))) {
            "Recovery resume should not get stuck on the generic heart-rate preparation screen"
        }
        require(waitForExternalSkipButton(40_000)) {
            "Skip button did not appear after resuming through the recovery dialog"
        }

        workoutDriver.clickText("Skip", 5_000)
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 3_000)

        val resumedSetVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            10_000
        )
        require(resumedSetVisible) {
            "Workout did not resume to the active set after skipping Polar connection from the recovery flow"
        }
    }

    private fun completeCurrentSetDeterministically(timeoutMs: Long = 15_000) {
        val completed = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = timeoutMs
        )
        require(completed) { "Failed to complete current set via workout state mutation helper" }
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

    private fun waitForPolarPreparingScreen(timeoutMs: Long): Boolean {
        return device.wait(Until.hasObject(By.text("Getting your Polar ready")), timeoutMs) ||
            device.wait(Until.hasObject(By.textContains("Polar device")), 2_000)
    }

    private fun waitForExternalSkipButton(timeoutMs: Long): Boolean {
        return device.wait(Until.hasObject(By.text("Skip")), timeoutMs)
    }

    private fun describeVisibleUi(): String {
        val labels = device.findObjects(By.text(Pattern.compile(".+")))
            .mapNotNull { runCatching { it.text }.getOrNull() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(12)
        val descriptions = device.findObjects(By.desc(Pattern.compile(".+")))
            .mapNotNull { runCatching { it.contentDescription }.getOrNull() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(12)
        return "texts=$labels descs=$descriptions"
    }
}
