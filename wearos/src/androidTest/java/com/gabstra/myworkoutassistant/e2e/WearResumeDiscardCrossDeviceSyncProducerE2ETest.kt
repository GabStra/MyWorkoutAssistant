package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDeviceSyncSpec
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearResumeDiscardCrossDeviceSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun discardRecoveredWorkout_syncsDiscardBackToPhone() {
        val dialogAppeared = workoutDriver.waitForRecoveryDialog(defaultTimeoutMs)
        require(dialogAppeared) {
            "Recovery dialog did not appear for '${ResumeCrossDeviceSyncSpec.WORKOUT_NAME}'."
        }

        val discarded = workoutDriver.clickRecoveryDiscard(timeoutMs = 10_000)
        require(discarded) {
            "Could not click Discard in the recovery dialog for '${ResumeCrossDeviceSyncSpec.WORKOUT_NAME}'."
        }

        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)
        val selectionVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), 10_000)
        require(selectionVisible) { "Workout selection screen did not reappear after discard." }

        assertWearDiscardClearedIncompleteState()
    }

    private fun assertWearDiscardClearedIncompleteState() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val unfinishedHistories = db.workoutHistoryDao().getAllWorkoutHistories().filter {
            !it.isDone &&
                it.workoutId == ResumeCrossDeviceSyncSpec.WORKOUT_ID &&
                it.globalId == ResumeCrossDeviceSyncSpec.WORKOUT_GLOBAL_ID
        }
        require(unfinishedHistories.isEmpty()) {
            "Wear still has unfinished histories after discard: ${unfinishedHistories.map { it.id }}"
        }

        val activeRecord = db.workoutRecordDao().getWorkoutRecordByWorkoutId(ResumeCrossDeviceSyncSpec.WORKOUT_ID)
        require(activeRecord == null) {
            "Wear still has an active workout record after discard: ${activeRecord?.id}"
        }
    }
}
