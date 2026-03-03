package com.gabstra.myworkoutassistant.e2e

import androidx.activity.ComponentActivity
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiObject2
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.lifecycle.ViewModelProvider
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWorkoutFlowHelper
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearVsLastComparisonE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var flowHelper: CrossDeviceWorkoutFlowHelper

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        runBlocking { retainOnlyPhoneSyncedHistoryOnWear() }
        CrossDeviceSyncWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        workoutDriver = createWorkoutDriver()
        flowHelper = CrossDeviceWorkoutFlowHelper(device, workoutDriver)
    }

    @Test
    fun completionProgression_usesSyncedHistoryForVsLast() = runBlocking {
        val syncedSnapshotForExerciseA = waitForSyncedPhoneHistoryOnWear()

        startWorkout(CrossDeviceSyncWorkoutStoreFixture.getWorkoutName())
        flowHelper.completeComplexWorkoutWithDeterministicModifications()
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)

        val complexARow = workoutDriver.findWithScrollFallback(
            selector = By.text("Complex A"),
            initialWaitMs = 4_000,
            directions = listOf(Direction.DOWN, Direction.UP)
        )
        require(complexARow != null) { "Could not find 'Complex A' progression row on completion screen." }

        val expectedVsLast = computeExpectedVsLastFromExecutedSets(
            exerciseId = CrossDeviceSyncWorkoutStoreFixture.EXERCISE_A_ID,
            syncedSnapshot = syncedSnapshotForExerciseA
        )
        val expectedStatus = expectedVsLast.name
        val detectedStatus = readLastStatusForRow(complexARow)
        require(detectedStatus == expectedStatus) {
            "Expected VS LAST to be $expectedStatus, detected=${detectedStatus ?: "NONE"}"
        }
    }

    private fun computeExpectedVsLastFromExecutedSets(
        exerciseId: java.util.UUID,
        syncedSnapshot: List<SimpleSet>
    ): Ternary {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var expected: Ternary? = null
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: error("No resumed activity found while validating VS LAST.")
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]

            val executed = viewModel.executedSetsHistory
                .filter { it.exerciseId == exerciseId }
                .mapNotNull { it.toSimpleSetOrNull() }
            require(executed.isNotEmpty()) { "No executed sets found for exercise $exerciseId." }

            expected = compareSetListsUnordered(executed, syncedSnapshot)
        }
        return expected ?: error("Failed to compute expected VS LAST.")
    }

    private fun SetHistory.toSimpleSetOrNull(): SimpleSet? {
        val setData = setData as? WeightSetData ?: return null
        return SimpleSet(weight = setData.actualWeight, reps = setData.actualReps)
    }

    private fun readLastStatusForRow(labelNode: UiObject2): String? {
        var container: UiObject2? = labelNode
        repeat(4) {
            val status = container?.findObject(By.descStartsWith("LAST:"))
                ?.contentDescription
                ?.toString()
                ?.substringAfter("LAST:")
            if (!status.isNullOrBlank()) return status
            container = container?.parent
        }
        return null
    }

    private suspend fun waitForSyncedPhoneHistoryOnWear(timeoutMs: Long = 120_000): List<SimpleSet> {
        val db = AppDatabase.getDatabase(ApplicationProvider.getApplicationContext())
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val history = workoutHistoryDao.getWorkoutHistoryById(
                CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID
            )
            if (history != null) {
                val syncedA1 = setHistoryDao.getSetHistoryByWorkoutHistoryIdAndSetId(
                    CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
                    CrossDeviceSyncWorkoutStoreFixture.SET_A1_ID
                )?.setData as? WeightSetData
                val syncedA2 = setHistoryDao.getSetHistoryByWorkoutHistoryIdAndSetId(
                    CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
                    CrossDeviceSyncWorkoutStoreFixture.SET_A2_ID
                )?.setData as? WeightSetData
                require(syncedA1 != null && syncedA2 != null) {
                    "Synced phone set histories for Complex A were not found on Wear."
                }
                require(syncedA1.actualReps == CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_REPS) {
                    "Synced A1 reps mismatch. expected=${CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_REPS} actual=${syncedA1.actualReps}"
                }
                require(syncedA2.actualReps == CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_REPS) {
                    "Synced A2 reps mismatch. expected=${CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_REPS} actual=${syncedA2.actualReps}"
                }
                return listOf(
                    SimpleSet(weight = syncedA1.actualWeight, reps = syncedA1.actualReps),
                    SimpleSet(weight = syncedA2.actualWeight, reps = syncedA2.actualReps)
                )
            }
            delay(2_000)
        }
        error("Synced phone history was not found on Wear within timeout.")
    }

    private suspend fun retainOnlyPhoneSyncedHistoryOnWear() {
        val db = AppDatabase.getDatabase(ApplicationProvider.getApplicationContext())
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()
        val keepId = CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID
        workoutHistoryDao.getAllWorkoutHistories()
            .filter { it.id != keepId }
            .forEach { history ->
                setHistoryDao.deleteByWorkoutHistoryId(history.id)
                workoutHistoryDao.deleteById(history.id)
            }
        db.workoutRecordDao().deleteAll()
    }
}
