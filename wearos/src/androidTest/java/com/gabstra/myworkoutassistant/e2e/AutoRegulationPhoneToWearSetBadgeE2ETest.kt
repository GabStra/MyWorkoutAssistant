package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.AutoRegulationSetBadgeFlowHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AutoRegulationPhoneToWearSetBadgeE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        retainOnlyPhoneSyncedHistoryOnWear()
        AutoRegulationSetBadgeWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun secondSession_usesPhoneSyncedHistoryForHistoricalBadge() {
        startWorkout(AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_NAME)
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
            "Phone-synced historical data for set ${AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID} " +
                "was not loaded into the Wear view model. historicalSetIds=$historicalSetIds"
        }

        AutoRegulationSetBadgeFlowHelper.advanceAdjustedSessionToSecondSet(
            workoutDriver = workoutDriver,
            device = device
        )
        AutoRegulationSetBadgeFlowHelper.assertHistoricalBadgeAndAdjustedWeight(
            workoutDriver = workoutDriver,
            device = device
        )

        workoutDriver.completeCurrentSet(timeoutMs = 20_000)
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
    }

    private fun retainOnlyPhoneSyncedHistoryOnWear() = runBlocking {
        val db = AppDatabase.getDatabase(ApplicationProvider.getApplicationContext())
        val keepId = AutoRegulationSetBadgeWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID
        db.workoutHistoryDao().getAllWorkoutHistories()
            .filter { it.id != keepId }
            .forEach { history ->
                db.setHistoryDao().deleteByWorkoutHistoryId(history.id)
                db.workoutRecordDao().deleteByWorkoutHistoryId(history.id)
                db.workoutHistoryDao().deleteById(history.id)
            }
    }
}
