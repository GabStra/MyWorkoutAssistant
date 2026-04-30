package com.gabstra.myworkoutassistant.e2e

import android.app.NotificationManager
import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.data.showTimerCompletedNotification
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutCompletionHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class WearRestNotificationRecoveryResumeE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun restNotificationReopen_thenRecoveryResume_completesOriginalWorkoutHistory() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        completeCurrentSetDeterministically()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val historySnapshot = captureActiveIncompleteHistorySnapshot()

        device.pressHome()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        workoutDriver.killAppProcessTimed(packageName = context.packageName, settleMs = 0)
        forceNotificationReopenIntoRecoveryPath()
        postTimerCompletionNotificationAndTap(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutGlobalId())

        require(enterWorkoutAfterNotificationReopen()) {
            "Could not return to the original workout after reopening from rest-complete notification. Visible UI: ${describeVisibleUi()}"
        }

        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 3_000)
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 3_000)

        WearWorkoutCompletionHelper.completeWorkoutViaStateMutations(
            device = device,
            context = context,
            maxSteps = 30,
            completionErrorMessage = "Workout did not complete after recovery resume from notification reopen."
        )

        assertOriginalWorkoutHistoryWasCompleted(historySnapshot)
    }

    private fun completeCurrentSetDeterministically(timeoutMs: Long = 15_000) {
        val completed = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = timeoutMs
        )
        require(completed) { "Failed to complete current set via workout state mutation helper" }
    }

    private fun captureActiveIncompleteHistorySnapshot(): ActiveHistorySnapshot = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val workoutHistory = waitForSingleUnfinishedWorkoutHistory(db)
        val setCount = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(workoutHistory.id).size
        val restCount = db.restHistoryDao().getByWorkoutHistoryIdOrdered(workoutHistory.id).size
        val workoutRecord = waitForWorkoutRecordForHistory(db, workoutHistory.id)

        require(setCount > 0) {
            "Expected at least one persisted set row before backgrounding on rest."
        }

        ActiveHistorySnapshot(
            historyId = workoutHistory.id,
            workoutId = workoutHistory.workoutId,
            setCount = setCount,
            restCount = restCount
        )
    }

    private suspend fun waitForSingleUnfinishedWorkoutHistory(db: AppDatabase): com.gabstra.myworkoutassistant.shared.WorkoutHistory {
        val deadline = System.currentTimeMillis() + 10_000
        while (System.currentTimeMillis() < deadline) {
            val unfinishedHistories = db.workoutHistoryDao().getAllUnfinishedWorkoutHistories()
            if (unfinishedHistories.size == 1) {
                return unfinishedHistories.single()
            }
            kotlinx.coroutines.delay(250)
        }
        val unfinishedHistories = db.workoutHistoryDao().getAllUnfinishedWorkoutHistories()
        error("Expected exactly one unfinished workout history while resting, found ${unfinishedHistories.size}: ${unfinishedHistories.map { it.id to it.workoutId }}")
    }

    private suspend fun waitForWorkoutRecordForHistory(
        db: AppDatabase,
        workoutHistoryId: UUID
    ): com.gabstra.myworkoutassistant.shared.WorkoutRecord {
        val deadline = System.currentTimeMillis() + 10_000
        while (System.currentTimeMillis() < deadline) {
            val workoutRecord = db.workoutRecordDao().getWorkoutRecordByWorkoutHistoryId(workoutHistoryId)
            if (workoutRecord != null) {
                return workoutRecord
            }
            kotlinx.coroutines.delay(250)
        }
        error("Expected workout_record row for unfinished history $workoutHistoryId while resting.")
    }

    private fun forceNotificationReopenIntoRecoveryPath() {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            .edit()
            .putBoolean("isWorkoutInProgress", false)
            .commit()
    }

    private fun postTimerCompletionNotificationAndTap(workoutGlobalId: UUID) {
        showTimerCompletedNotification(
            context = context,
            workoutGlobalId = workoutGlobalId,
            title = "Rest finished",
            message = "Tap to continue workout"
        )

        val notificationManager =
            context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val deadline = System.currentTimeMillis() + 10_000
        while (System.currentTimeMillis() < deadline) {
            val timerNotification = notificationManager.activeNotifications.firstOrNull {
                it.notification.channelId == "timer_completion_channel"
            }
            val contentIntent = timerNotification?.notification?.contentIntent
            if (contentIntent != null) {
                contentIntent.send()
                device.wait(Until.hasObject(By.pkg(context.packageName).depth(0)), 10_000)
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                return
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        error("Timer completion notification was not available to tap.")
    }

    private fun enterWorkoutAfterNotificationReopen(): Boolean {
        val workoutVisible = waitForActiveWorkoutScreen(8_000)
        if (workoutVisible) {
            return true
        }

        if (!workoutDriver.waitForRecoveryDialog(20_000)) {
            return waitForActiveWorkoutScreen(5_000)
        }

        val resumed = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName(),
            inWorkoutSelector = By.descContains(SetValueSemantics.WeightSetTypeDescription),
            timeoutMs = 20_000,
            useRestartTimer = false
        )
        return resumed.enteredWorkout || waitForActiveWorkoutScreen(5_000)
    }

    private fun waitForActiveWorkoutScreen(timeoutMs: Long): Boolean {
        return device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            timeoutMs
        ) || device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            2_000
        )
    }

    private fun assertOriginalWorkoutHistoryWasCompleted(snapshot: ActiveHistorySnapshot) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val completedOriginalHistory = db.workoutHistoryDao().getWorkoutHistoryById(snapshot.historyId)
            ?: error("Original workout history ${snapshot.historyId} no longer exists after resume.")
        val allHistoriesForWorkout = db.workoutHistoryDao().getWorkoutsByWorkoutId(snapshot.workoutId)
        val completedSets = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(snapshot.historyId)
        val completedRests = db.restHistoryDao().getByWorkoutHistoryIdOrdered(snapshot.historyId)

        require(completedOriginalHistory.isDone) {
            "BUG REPRODUCED: original workout history ${snapshot.historyId} remained unfinished after recovery resume."
        }
        require(allHistoriesForWorkout.size == 1) {
            "BUG REPRODUCED: recovery resume created an extra workout history row for workoutId=${snapshot.workoutId}. histories=${allHistoriesForWorkout.map { it.id to it.isDone }}"
        }
        require(completedSets.size >= snapshot.setCount) {
            "BUG REPRODUCED: resumed workout lost pre-existing set rows. before=${snapshot.setCount} after=${completedSets.size}"
        }
        require(completedRests.size >= snapshot.restCount) {
            "BUG REPRODUCED: resumed workout lost pre-existing rest rows. before=${snapshot.restCount} after=${completedRests.size}"
        }
    }

    private fun describeVisibleUi(): String {
        val labels = device.findObjects(By.textStartsWith(""))
            .mapNotNull { runCatching { it.text }.getOrNull() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(12)
        val descriptions = device.findObjects(By.descStartsWith(""))
            .mapNotNull { runCatching { it.contentDescription }.getOrNull() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(12)
        return "texts=$labels descs=$descriptions"
    }

    private data class ActiveHistorySnapshot(
        val historyId: UUID,
        val workoutId: UUID,
        val setCount: Int,
        val restCount: Int
    )
}
