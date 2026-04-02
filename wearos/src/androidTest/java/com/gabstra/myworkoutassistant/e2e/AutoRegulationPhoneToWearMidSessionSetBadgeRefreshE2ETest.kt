package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.DataLayerListenerService
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.AutoRegulationSetBadgeFlowHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class AutoRegulationPhoneToWearMidSessionSetBadgeRefreshE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        clearAllWorkoutHistories()
        AutoRegulationSetBadgeWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun incomingPhoneHistory_midSessionRefreshesBadgeUsingLatestSameDayHistory() {
        startWorkout(AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_NAME)
        AutoRegulationSetBadgeFlowHelper.advanceAdjustedSessionToSecondSet(
            workoutDriver = workoutDriver,
            device = device
        )

        require(
            !AutoRegulationSetBadgeFlowHelper.waitForHistoricalWeightInViewModel(
                exerciseId = AutoRegulationSetBadgeWorkoutStoreFixture.EXERCISE_ID,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                expectedWeight = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT,
                timeoutMs = 1_500
            )
        ) {
            "Historical data was already loaded before the simulated phone sync."
        }
        require(
            !device.wait(
                Until.hasObject(By.text(AutoRegulationSetBadgeWorkoutStoreFixture.EXPECTED_BADGE_TEXT)),
                1_500
            )
        ) {
            "Historical delta badge was visible before the simulated phone sync."
        }

        seedPhoneSyncedHistoriesOnWear()
        triggerWorkoutStoreRefreshReceiver()

        require(
            AutoRegulationSetBadgeFlowHelper.waitForHistoricalWeightInViewModel(
                exerciseId = AutoRegulationSetBadgeWorkoutStoreFixture.EXERCISE_ID,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                expectedWeight = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT
            )
        ) {
            val historicalSetIds = WearWorkoutStateMutationHelper.getHistoricalSetIds(
                AutoRegulationSetBadgeWorkoutStoreFixture.EXERCISE_ID
            )
            "Latest phone-synced history was not reloaded into the active Wear session. historicalSetIds=$historicalSetIds"
        }
        require(waitForCurrentSetScreenAfterRefresh()) {
            "Wear did not return to the second weight set screen after syncing phone history."
        }

        AutoRegulationSetBadgeFlowHelper.assertHistoricalBadgeAndAdjustedWeight(
            workoutDriver = workoutDriver,
            device = device
        )
    }

    private fun clearAllWorkoutHistories() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        db.restHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()
        db.workoutHistoryDao().deleteAll()
    }

    private fun seedPhoneSyncedHistoriesOnWear() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val olderStart = LocalDateTime.of(LocalDate.now(), LocalTime.of(8, 0))
        val latestStart = olderStart.plusHours(2)
        val olderHistoryId = UUID.randomUUID()
        val latestHistoryId = UUID.randomUUID()

        db.workoutHistoryDao().insertAll(
            WorkoutHistory(
                id = olderHistoryId,
                workoutId = AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_ID,
                date = olderStart.toLocalDate(),
                time = olderStart.toLocalTime(),
                startTime = olderStart,
                duration = 600,
                heartBeatRecords = listOf(105, 110, 112),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_GLOBAL_ID,
                version = 1u
            ),
            WorkoutHistory(
                id = latestHistoryId,
                workoutId = AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_ID,
                date = latestStart.toLocalDate(),
                time = latestStart.toLocalTime(),
                startTime = latestStart,
                duration = 600,
                heartBeatRecords = listOf(108, 114, 118),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_GLOBAL_ID,
                version = 2u
            )
        )

        db.setHistoryDao().insertAll(
            createSetHistory(
                workoutHistoryId = olderHistoryId,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_1_ID,
                order = 0u,
                startTime = olderStart.plusMinutes(1),
                actualWeight = 77.5,
                executionSequence = 1u
            ),
            createSetHistory(
                workoutHistoryId = olderHistoryId,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                order = 1u,
                startTime = olderStart.plusMinutes(3),
                actualWeight = 77.5,
                executionSequence = 2u
            ),
            createSetHistory(
                workoutHistoryId = latestHistoryId,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_1_ID,
                order = 0u,
                startTime = latestStart.plusMinutes(1),
                actualWeight = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT,
                executionSequence = 1u
            ),
            createSetHistory(
                workoutHistoryId = latestHistoryId,
                setId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                order = 1u,
                startTime = latestStart.plusMinutes(3),
                actualWeight = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT,
                executionSequence = 2u
            )
        )
    }

    private fun createSetHistory(
        workoutHistoryId: UUID,
        setId: UUID,
        order: UInt,
        startTime: LocalDateTime,
        actualWeight: Double,
        executionSequence: UInt
    ): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = workoutHistoryId,
            exerciseId = AutoRegulationSetBadgeWorkoutStoreFixture.EXERCISE_ID,
            setId = setId,
            order = order,
            startTime = startTime,
            endTime = startTime.plusMinutes(1),
            setData = WeightSetData(
                actualReps = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS,
                actualWeight = actualWeight,
                volume = AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS * actualWeight
            ),
            skipped = false,
            executionSequence = executionSequence,
            version = 2u
        )
    }

    private fun triggerWorkoutStoreRefreshReceiver() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? MainActivity
                ?: error("No resumed MainActivity found while triggering workout-store refresh.")
            val receiverField = MainActivity::class.java.getDeclaredField("myReceiver")
            receiverField.isAccessible = true
            val receiver = receiverField.get(activity) as android.content.BroadcastReceiver
            receiver.onReceive(
                activity,
                android.content.Intent(DataLayerListenerService.INTENT_ID).apply {
                    putExtra(DataLayerListenerService.WORKOUT_STORE_JSON, "{}")
                }
            )
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    private fun waitForCurrentSetScreenAfterRefresh(timeoutMs: Long = 20_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val onExpectedSet =
                WearWorkoutStateMutationHelper.getCurrentSetId() ==
                    AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID
            if (onExpectedSet && workoutDriver.waitForWeightSetScreen(1_000)) {
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }
}
