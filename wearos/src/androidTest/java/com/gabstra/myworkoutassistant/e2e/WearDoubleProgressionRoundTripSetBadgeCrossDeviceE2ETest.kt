package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.DoubleProgressionRoundTripBadgeFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class WearDoubleProgressionRoundTripSetBadgeCrossDeviceE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        // Preserve the phone-synced history for the first start. This test only clears Wear state
        // after session 1 to force the explicit phone -> Wear round trip.
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun repeatedPhoneRoundTrip_doubleProgressionStillShowsHistoricalBadge() = runBlocking {
        startWorkout(DoubleProgressionRoundTripBadgeFixture.WORKOUT_NAME)
        assertCurrentSet(
            expectedReps = DoubleProgressionRoundTripBadgeFixture.FIRST_WEAR_SESSION_REPS,
            expectedWeight = DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT,
            timeoutMs = 10_000
        )
        assertHistoricalSet(expectedReps = DoubleProgressionRoundTripBadgeFixture.PREVIOUS_SESSION_REPS)
        assertBadgeVisible()
        workoutDriver.completeCurrentSet(timeoutMs = 20_000)
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)

        resetWearToRequirePhoneRoundTrip()
        waitForPhoneRoundTripState(
            expectedHistoricalReps = DoubleProgressionRoundTripBadgeFixture.FIRST_WEAR_SESSION_REPS,
            expectedTemplateReps = DoubleProgressionRoundTripBadgeFixture.FIRST_WEAR_SESSION_REPS,
            timeoutMs = E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        )

        launchAppFromHome()
        startWorkout(DoubleProgressionRoundTripBadgeFixture.WORKOUT_NAME)
        assertCurrentSet(
            expectedReps = DoubleProgressionRoundTripBadgeFixture.SECOND_WEAR_SESSION_REPS,
            expectedWeight = DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT,
            timeoutMs = 15_000
        )
        assertHistoricalSet(expectedReps = DoubleProgressionRoundTripBadgeFixture.FIRST_WEAR_SESSION_REPS)
        assertBadgeVisible()
        workoutDriver.completeCurrentSet(timeoutMs = 20_000)
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private suspend fun resetWearToRequirePhoneRoundTrip() {
        workoutDriver.killAppProcess(packageName = context.packageName, settleMs = 0)
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
        ApplicationProvider.getApplicationContext<android.content.Context>()
            .deleteFile("workout_store.json")
        delay(1_000)
    }

    private suspend fun waitForPhoneRoundTripState(
        expectedHistoricalReps: Int,
        expectedTemplateReps: Int,
        timeoutMs: Long
    ) {
        val repository = WorkoutStoreRepository(context.filesDir)
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            val syncedExercise = repository.getWorkoutStore().workouts
                .firstOrNull {
                    it.id == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
                }
                ?.workoutComponents
                ?.singleOrNull() as? Exercise
            val syncedSet = syncedExercise?.sets?.singleOrNull() as? WeightSet

            val latestHistory = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .filter {
                    it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID &&
                        it.globalId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_GLOBAL_ID
                }
                .maxByOrNull { it.startTime }
            val historicalSet = latestHistory?.let {
                db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(it.id, DoubleProgressionRoundTripBadgeFixture.SET_ID)
            }?.setData as? WeightSetData

            if (
                syncedSet?.reps == expectedTemplateReps &&
                syncedSet.weight.let { abs(it - DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT) <= DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE } &&
                historicalSet?.actualReps == expectedHistoricalReps &&
                abs(historicalSet.actualWeight - DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT) <= DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE
            ) {
                return
            }
            delay(500)
        }

        val currentStoreReps = (repository.getWorkoutStore().workouts
            .firstOrNull { it.id == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID }
            ?.workoutComponents
            ?.singleOrNull() as? Exercise)
            ?.sets
            ?.singleOrNull()
            ?.let { it as? WeightSet }
            ?.reps
        val historicalSummaries = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
            .filter { it.workoutId == DoubleProgressionRoundTripBadgeFixture.WORKOUT_ID }
            .map { history ->
                val setData = db.setHistoryDao()
                    .getSetHistoryByWorkoutHistoryIdAndSetId(history.id, DoubleProgressionRoundTripBadgeFixture.SET_ID)
                    ?.setData as? WeightSetData
                "${history.id}:${setData?.actualReps}@${setData?.actualWeight}"
            }
        error(
            "Timed out waiting for phone round-trip state on Wear. " +
                "expectedHistoricalReps=$expectedHistoricalReps, expectedTemplateReps=$expectedTemplateReps, " +
                "currentStoreReps=$currentStoreReps, histories=$historicalSummaries"
        )
    }

    private fun assertCurrentSet(
        expectedReps: Int,
        expectedWeight: Double,
        timeoutMs: Long
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val currentSetData = WearWorkoutStateMutationHelper.getCurrentWeightSetData()
            if (
                currentSetData != null &&
                currentSetData.actualReps == expectedReps &&
                abs(currentSetData.actualWeight - expectedWeight) <= DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE
            ) {
                return
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        val currentSetData = WearWorkoutStateMutationHelper.getCurrentWeightSetData()
        error("Expected current set ${expectedWeight}kg x $expectedReps, actual=$currentSetData")
    }

    private fun assertHistoricalSet(expectedReps: Int, timeoutMs: Long = 10_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val historical = WearWorkoutStateMutationHelper.getHistoricalWeightSetData(
                DoubleProgressionRoundTripBadgeFixture.EXERCISE_ID,
                DoubleProgressionRoundTripBadgeFixture.SET_ID
            )
            if (
                historical != null &&
                historical.actualReps == expectedReps &&
                abs(historical.actualWeight - DoubleProgressionRoundTripBadgeFixture.TEMPLATE_WEIGHT) <= DoubleProgressionRoundTripBadgeFixture.WEIGHT_TOLERANCE
            ) {
                return
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        val historicalSetIds = WearWorkoutStateMutationHelper.getHistoricalSetIds(
            DoubleProgressionRoundTripBadgeFixture.EXERCISE_ID
        )
        error("Expected historical set reps=$expectedReps to be loaded on Wear. historicalSetIds=$historicalSetIds")
    }

    private fun assertBadgeVisible(timeoutMs: Long = 10_000) {
        val badgeVisible = device.wait(
            Until.hasObject(By.text(DoubleProgressionRoundTripBadgeFixture.EXPECTED_BADGE_TEXT)),
            timeoutMs
        )
        require(badgeVisible) {
            val currentSetData = WearWorkoutStateMutationHelper.getCurrentWeightSetData()
            val historicalSetIds = WearWorkoutStateMutationHelper.getHistoricalSetIds(
                DoubleProgressionRoundTripBadgeFixture.EXERCISE_ID
            )
            "Expected historical delta badge '${DoubleProgressionRoundTripBadgeFixture.EXPECTED_BADGE_TEXT}'. " +
                "currentSet=$currentSetData, historicalSetIds=$historicalSetIds"
        }
    }

}
