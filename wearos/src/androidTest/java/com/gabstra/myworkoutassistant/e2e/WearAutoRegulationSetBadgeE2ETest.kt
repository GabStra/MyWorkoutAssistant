package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.AutoRegulationSetBadgeFlowHelper
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearAutoRegulationSetBadgeE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        AutoRegulationSetBadgeWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun secondSession_showsHistoricalBadgeOnAdjustedSecondSet() {
        startWorkout(AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_NAME)
        AutoRegulationSetBadgeFlowHelper.completeBaselineSession(
            workoutDriver = workoutDriver,
            device = device
        )
        AutoRegulationSetBadgeFlowHelper.waitForCompletedHistoryCount(
            context = context,
            expectedCount = 1
        )

        workoutDriver.goHomeAndVerifySelection()

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
            "Historical session data for set ${AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID} " +
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
}
