package com.gabstra.myworkoutassistant.e2e

import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ResumeCrossDeviceSyncSpec
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearResumeDiscardCrossDeviceSyncProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
    }

    override fun shouldClearPersistedE2eState(): Boolean = false

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun discardRecoveredWorkout_syncsDiscardBackToPhone() {
        waitForResumedMainActivity()
        discardViaWearViewModel()
        assertWearDiscardClearedIncompleteState()
        runBlocking { delay(3_000) }
    }

    private fun waitForResumedMainActivity(timeoutMs: Long = 12_000L) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val hasResumedActivity = InstrumentationRegistry.getInstrumentation().run {
                var found = false
                runOnMainSync {
                    found = ActivityLifecycleMonitorRegistry.getInstance()
                        .getActivitiesInStage(Stage.RESUMED)
                        .any { it is MainActivity }
                }
                found
            }
            if (hasResumedActivity) {
                return
            }
            SystemClock.sleep(200)
        }
        error("No resumed MainActivity found before discard.")
    }

    private fun discardViaWearViewModel() {
        assertWearHasIncompleteState()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var discardJob: Job? = null
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? MainActivity
                ?: error("No resumed MainActivity found while discarding incomplete workout on Wear.")
            val appViewModel = resolveAppViewModel(activity)
            appViewModel.prepareResumeWorkout(
                ResumeCrossDeviceSyncSpec.WORKOUT_ID,
                ResumeCrossDeviceSyncSpec.INCOMPLETE_HISTORY_ID
            )
            discardJob = appViewModel.discardCurrentIncompleteWorkout()
        }
        runBlocking {
            requireNotNull(discardJob) {
                "Wear discard did not start because no active incomplete workout record was found."
            }.join()
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    private fun assertWearHasIncompleteState() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val activeRecord = db.workoutRecordDao().getWorkoutRecordByWorkoutId(ResumeCrossDeviceSyncSpec.WORKOUT_ID)
        val activeHistory = activeRecord?.let { db.workoutHistoryDao().getWorkoutHistoryById(it.workoutHistoryId) }
        require(activeRecord != null && activeHistory != null && !activeHistory.isDone) {
            "Wear discard producer did not start with an incomplete synced state. " +
                "record=${activeRecord?.id} history=${activeHistory?.id} historyDone=${activeHistory?.isDone}"
        }
    }

    private fun resolveAppViewModel(activity: MainActivity): com.gabstra.myworkoutassistant.data.AppViewModel {
        val activityClass = MainActivity::class.java
        activityClass.declaredFields.firstOrNull {
            com.gabstra.myworkoutassistant.data.AppViewModel::class.java.isAssignableFrom(it.type)
        }?.let { field ->
            field.isAccessible = true
            return field.get(activity) as com.gabstra.myworkoutassistant.data.AppViewModel
        }

        activityClass.declaredFields.firstOrNull {
            it.name.contains("appViewModel", ignoreCase = true) &&
                kotlin.Lazy::class.java.isAssignableFrom(it.type)
        }?.let { field ->
            field.isAccessible = true
            val lazyValue = field.get(activity) as Lazy<*>
            return lazyValue.value as com.gabstra.myworkoutassistant.data.AppViewModel
        }

        error(
            "Could not resolve AppViewModel from MainActivity fields: ${
                activityClass.declaredFields.joinToString { "${it.name}:${it.type.simpleName}" }
            }"
        )
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
