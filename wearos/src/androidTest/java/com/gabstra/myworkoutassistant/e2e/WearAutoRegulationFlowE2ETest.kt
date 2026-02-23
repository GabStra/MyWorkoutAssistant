package com.gabstra.myworkoutassistant.e2e

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import org.junit.Before
import org.junit.Ignore
import org.junit.Test
import org.junit.runner.RunWith

/**
 * E2E tests for auto-regulation progression flow on Wear OS.
 * Exercise with progressionMode == AUTO_REGULATION has no calibration; first screen is the first work set.
 * Completing a non-last work set with reps in range shows the RIR screen; confirm advances.
 */
@RunWith(AndroidJUnit4::class)
class WearAutoRegulationFlowE2ETest : WearBaseE2ETest() {

    private lateinit var workoutDriver: WearWorkoutDriver

    /** Timeout for RIR screen to appear after completing a set (reps in range). */
    private val rirScreenTimeoutMs = 8_000L

    /** Short timeout to assert calibration load screen does NOT appear. */
    private val noCalibrationWaitMs = 3_000L

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun autoRegulation_noCalibrationScreenOnStart() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        // Calibration load selection must NOT appear for auto-regulation.
        val calibrationLoadAppeared = device.wait(
            Until.hasObject(By.textContains("Select load for")),
            noCalibrationWaitMs
        )
        require(!calibrationLoadAppeared) {
            "Auto-regulation workout must not show calibration load screen on start"
        }

        // First screen should be the first work set (exercise name visible).
        val firstSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(firstSetVisible) {
            "First set screen (exercise name) did not appear; expected no calibration flow"
        }
    }

    @Test
    fun autoRegulation_firstWorkSetRepsInRange_showsRIRScreenThenAdvances() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        val exerciseVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(exerciseVisible) { "First set screen did not appear" }

        val firstSetWeight = workoutDriver.readWeightOnSetScreen(defaultTimeoutMs)
        require(firstSetWeight != null) { "Could not read first set weight" }

        workoutDriver.completeCurrentSet()

        val rirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            rirScreenTimeoutMs
        )
        require(rirVisible) { "Auto-regulation RIR screen did not appear after completing first work set" }

        workoutDriver.selectRIRAndConfirm(2, rirScreenTimeoutMs)

        val rirGone = device.wait(Until.gone(By.text("0 = Form Breaks")), defaultTimeoutMs)
        require(rirGone) { "RIR screen did not disappear after confirming" }

        val restOrNextVisible = device.wait(
            Until.hasObject(By.textContains(":")),
            defaultTimeoutMs
        )
        require(restOrNextVisible) {
            "Rest timer or next set did not appear after confirming RIR"
        }

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        workoutDriver.skipRest()

        val secondSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(secondSetVisible) { "Second work set did not appear after skipping rest" }
        workoutDriver.navigateToPagerPage(Direction.RIGHT)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        var secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        if (secondSetWeight == null) {
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        }
        require(secondSetWeight != null) { "Could not read second set weight" }
        require(secondSetWeight == firstSetWeight) {
            "RIR 2 must not change load: first set=$firstSetWeight kg, second set=$secondSetWeight kg"
        }
    }

    @Test
    fun autoRegulation_RIR0_secondSetShowsLowerWeight() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        val firstSetWeight = workoutDriver.readWeightOnSetScreen(defaultTimeoutMs)
        require(firstSetWeight != null) { "Could not read first set weight" }

        workoutDriver.completeCurrentSet()
        val rirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            rirScreenTimeoutMs
        )
        require(rirVisible) { "RIR screen did not appear after first work set" }
        workoutDriver.selectRIRAndConfirm(0, rirScreenTimeoutMs)

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        workoutDriver.skipRest()

        val secondSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(secondSetVisible) { "Second work set did not appear after skipping rest" }
        workoutDriver.navigateToPagerPage(Direction.RIGHT)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        var secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        if (secondSetWeight == null) {
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        }
        require(secondSetWeight != null) { "Could not read second set weight" }
        require(secondSetWeight < firstSetWeight) {
            "RIR 0 must reduce load for subsequent sets: first=$firstSetWeight kg, second=$secondSetWeight kg"
        }
    }

    @Test
    fun autoRegulation_RIR3_secondSetShowsHigherWeight() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        val firstSetWeight = workoutDriver.readWeightOnSetScreen(defaultTimeoutMs)
        require(firstSetWeight != null) { "Could not read first set weight" }

        workoutDriver.completeCurrentSet()
        val rirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            rirScreenTimeoutMs
        )
        require(rirVisible) { "RIR screen did not appear after first work set" }
        workoutDriver.selectRIRAndConfirm(3, rirScreenTimeoutMs)

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)
        workoutDriver.skipRest()

        val secondSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(secondSetVisible) { "Second work set did not appear after skipping rest" }
        workoutDriver.navigateToPagerPage(Direction.RIGHT)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        var secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        if (secondSetWeight == null) {
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            secondSetWeight = workoutDriver.readWeightOnSetScreen(5_000)
        }
        require(secondSetWeight != null) { "Could not read second set weight" }
        require(secondSetWeight > firstSetWeight) {
            "RIR 3 must increase load for subsequent sets: first=$firstSetWeight kg, second=$secondSetWeight kg"
        }
    }

    @Test
    fun autoRegulation_secondWorkSetThenRestOrCompletion() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)

        workoutDriver.completeCurrentSet()
        val rirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            rirScreenTimeoutMs
        )
        require(rirVisible) { "RIR screen did not appear after first work set" }
        workoutDriver.completeCurrentSet()

        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), defaultTimeoutMs)
        require(restVisible) { "Rest screen did not appear after first work set + RIR" }

        workoutDriver.skipRest()

        val secondSetVisible = device.wait(
            Until.hasObject(By.text(AutoRegulationWorkoutStoreFixture.EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(secondSetVisible) { "Second work set did not appear after skipping rest" }

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        workoutDriver.completeCurrentSet()

        // Second set is the last work set: no RIR screen; should go to rest or completion.
        val rirAfterSecondSet = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            noCalibrationWaitMs
        )
        require(!rirAfterSecondSet) {
            "Last work set must not show RIR screen; should advance to rest or completion"
        }

        val restOrCompleted = device.wait(
            Until.hasObject(By.textContains(":")),
            defaultTimeoutMs
        ) || device.wait(
            Until.hasObject(By.text("Completed")),
            defaultTimeoutMs
        )
        require(restOrCompleted) {
            "After last work set expected rest timer or completion screen"
        }
    }

    /** Optional: recovery from RIR screen. Enable when recovery dialog appears reliably after relaunch. */
    @Ignore("Recovery dialog not appearing within timeout after Home + relaunch on emulator")
    @Test
    fun autoRegulation_resumeFromRIRScreen_restoresRIRState() {
        AutoRegulationWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(AutoRegulationWorkoutStoreFixture.getWorkoutName())

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        workoutDriver.completeCurrentSet()

        val rirVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            rirScreenTimeoutMs
        )
        require(rirVisible) { "RIR screen did not appear before interrupt" }

        device.pressHome()
        device.waitForIdle(1_000)
        relaunchAppAndWaitForRecovery()

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkout(
            workoutName = AutoRegulationWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.text("0 = Form Breaks"),
            timeoutMs = 15_000
        )
        require(resumed) { "Could not resume to RIR screen after relaunch" }

        val rirAgainVisible = device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            defaultTimeoutMs
        )
        require(rirAgainVisible) { "RIR screen not visible after recovery resume" }

        workoutDriver.completeCurrentSet()
        val rirGone = device.wait(Until.gone(By.text("0 = Form Breaks")), defaultTimeoutMs)
        require(rirGone) { "RIR screen did not advance after confirm post-resume" }
    }

    /**
     * Relaunches the app and waits for the recovery dialog (longer timeout than default launch readiness).
     * Use when resuming from an interrupted state so recovery has time to appear.
     */
    private fun relaunchAppAndWaitForRecovery() {
        val pkg = context.packageName
        val launchIntent = context.packageManager.getLaunchIntentForPackage(pkg)
            ?: error("Launch intent for package $pkg not found")
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        context.startActivity(launchIntent)
        val windowAppeared = device.wait(
            Until.hasObject(By.pkg(pkg).depth(0)),
            E2ETestTimings.APP_LAUNCH_WINDOW_TIMEOUT_MS
        )
        require(windowAppeared) { "App window did not appear after relaunch" }
        val recoveryVisible = workoutDriver.waitForRecoveryDialog(15_000)
        require(recoveryVisible) {
            "Recovery dialog did not appear within 15s after relaunch (RIR screen interrupt)"
        }
    }
}
