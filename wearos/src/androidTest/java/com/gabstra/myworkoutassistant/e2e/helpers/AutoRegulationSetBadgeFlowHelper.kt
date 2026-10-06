package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.sync.WorkoutHistorySyncWorker
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import java.util.UUID
import kotlin.math.abs

object AutoRegulationSetBadgeFlowHelper {
    fun completeBaselineSession(
        workoutDriver: WearWorkoutDriver,
        device: UiDevice
    ) {
        require(waitForCurrentSetId(AutoRegulationSetBadgeWorkoutStoreFixture.SET_1_ID)) {
            "Baseline session did not reach the first work set."
        }
        require(
            WearWorkoutStateMutationHelper.completeCurrentAutoRegulationSet(
                device = device,
                timeoutMs = 20_000
            )
        ) {
            "Failed to complete the baseline auto-regulation set through the auto-regulation path."
        }
        require(
            skipRestWhenReady(
                device = device,
                expectedNextSetId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                timeoutMs = 20_000
            )
        ) { "Baseline session did not advance to the second work set." }
        require(waitForCurrentSetId(AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID)) {
            "Baseline session did not advance to the second work set."
        }
        require(
            WearWorkoutStateMutationHelper.completeCurrentSet(
                device = device,
                context = ApplicationProvider.getApplicationContext(),
                timeoutMs = 10_000
            )
        ) { "Failed to complete the baseline session's second work set." }
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
    }

    fun advanceAdjustedSessionToSecondSet(
        workoutDriver: WearWorkoutDriver,
        device: UiDevice,
    ) {
        require(waitForCurrentSetId(AutoRegulationSetBadgeWorkoutStoreFixture.SET_1_ID)) {
            "Adjusted session did not reach the first work set."
        }
        require(
            WearWorkoutStateMutationHelper.updateCurrentWeightSet(
                device = device,
                actualReps = AutoRegulationSetBadgeWorkoutStoreFixture.SECOND_SESSION_FIRST_SET_REPS
            )
        ) {
            "Failed to edit the first auto-regulation set reps before completion."
        }
        require(
            WearWorkoutStateMutationHelper.completeCurrentAutoRegulationSet(
                device = device,
                timeoutMs = 20_000
            )
        ) {
            "Failed to complete the adjusted auto-regulation set through the auto-regulation path."
        }
        require(
            skipRestWhenReady(
                device = device,
                expectedNextSetId = AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID,
                timeoutMs = 20_000
            )
        ) { "Adjusted session did not advance to the second work set." }
        require(waitForCurrentSetId(AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID)) {
            "Adjusted session did not advance to the second work set."
        }
    }

    fun assertHistoricalBadgeAndAdjustedWeight(
        workoutDriver: WearWorkoutDriver,
        device: UiDevice,
        timeoutMs: Long = 10_000
    ) {
        val badgeVisible = waitForHistoricalBadge(device = device, timeoutMs = timeoutMs)
        val displayedWeight = workoutDriver.readWeightOnSetScreen(timeoutMs = timeoutMs)
        val expectedWeight = AutoRegulationSetBadgeWorkoutStoreFixture.EXPECTED_ADJUSTED_SECOND_SET_WEIGHT
        require(
            displayedWeight != null &&
                abs(displayedWeight - expectedWeight) <= AutoRegulationSetBadgeWorkoutStoreFixture.WEIGHT_TOLERANCE
        ) {
            "Expected adjusted second-set weight $expectedWeight kg, actual=$displayedWeight."
        }
        require(badgeVisible) {
            val comparisonSnapshot = WearWorkoutStateMutationHelper.getCurrentWeightSetComparisonSnapshot()
            val historicalSetIds = WearWorkoutStateMutationHelper.getHistoricalSetIds(
                AutoRegulationSetBadgeWorkoutStoreFixture.EXERCISE_ID
            )
            val previousSetData = comparisonSnapshot?.previousSetData
            val currentSetData = comparisonSnapshot?.currentSetData
            require(
                previousSetData != null &&
                    currentSetData != null &&
                    abs(previousSetData.actualWeight - AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
                    AutoRegulationSetBadgeWorkoutStoreFixture.WEIGHT_TOLERANCE &&
                    currentSetData.actualWeight >= previousSetData.actualWeight
            ) {
                "Expected historical delta badge '${AutoRegulationSetBadgeWorkoutStoreFixture.EXPECTED_BADGE_TEXT}' " +
                    "on the second set screen. Current weight=$displayedWeight, " +
                    "previousSetData=$previousSetData, currentSetData=$currentSetData, " +
                    "historicalSetIds=$historicalSetIds."
            }
            return
        }
    }

    private fun waitForHistoricalBadge(
        device: UiDevice,
        timeoutMs: Long
    ): Boolean {
        val expectedText = AutoRegulationSetBadgeWorkoutStoreFixture.EXPECTED_BADGE_TEXT
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val visible =
                device.hasObject(By.text(expectedText)) ||
                device.hasObject(By.desc(expectedText))
            if (visible) {
                return true
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    fun waitForHistoricalWeightInViewModel(
        exerciseId: UUID,
        setId: UUID,
        expectedWeight: Double,
        timeoutMs: Long = 10_000
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val historical = WearWorkoutStateMutationHelper.getHistoricalWeightSetData(exerciseId, setId)
            if (historical != null && abs(historical.actualWeight - expectedWeight) <= 0.01) {
                return true
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    fun waitForCompletedHistoryCount(
        context: Context,
        expectedCount: Int,
        timeoutMs: Long = 20_000
    ) {
        runBlocking {
            val db = AppDatabase.getDatabase(ApplicationProvider.getApplicationContext())
            val deadline = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < deadline) {
                val completedCount = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                    .count { it.workoutId == AutoRegulationSetBadgeWorkoutStoreFixture.WORKOUT_ID }
                if (completedCount >= expectedCount) {
                    return@runBlocking
                }
                delay(500)
            }
            error("Expected at least $expectedCount completed auto-regulation histories on Wear within ${timeoutMs}ms.")
        }
    }

    fun waitForCompletedHistoryCountAndEnqueueSync(
        context: Context,
        expectedCount: Int,
        timeoutMs: Long = 20_000
    ) {
        waitForCompletedHistoryCount(
            context = context,
            expectedCount = expectedCount,
            timeoutMs = timeoutMs
        )
        WorkoutHistorySyncWorker.enqueue(context)
    }

    private fun waitForCurrentSetId(expectedSetId: UUID, timeoutMs: Long = 10_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (WearWorkoutStateMutationHelper.getCurrentSetId() == expectedSetId) {
                return true
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    private fun skipRestWhenReady(
        device: UiDevice,
        expectedNextSetId: UUID,
        timeoutMs: Long
    ): Boolean {
        if (WearWorkoutStateMutationHelper.getCurrentSetId() == expectedNextSetId) {
            return true
        }

        WearWorkoutStateMutationHelper.skipCurrentRest(
            device = device,
            timeoutMs = timeoutMs.coerceAtMost(5_000)
        )
        return waitForCurrentSetId(expectedNextSetId, timeoutMs = timeoutMs)
    }
}
