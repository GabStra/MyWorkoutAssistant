package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiObject2
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CompletionVsLastWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearCompletionVsLastE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        CompletionVsLastWorkoutStoreFixture.setupWorkoutStore(context)
        seedPreviousCompletedHistory()
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun completionProgression_marksVsLastAbove_whenSetIsEditedOnWear() {
        startWorkout(CompletionVsLastWorkoutStoreFixture.getWorkoutName())

        val modified = modifyCurrentRepsByPlusOne()
        require(modified) { "Failed to increment reps before completing the set." }

        val completed = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = 20_000
        )
        require(completed) { "Failed to complete the set after incrementing reps." }
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)

        val row = workoutDriver.findWithScrollFallback(
            selector = By.text(CompletionVsLastWorkoutStoreFixture.EXERCISE_NAME),
            initialWaitMs = 4_000,
            directions = listOf(Direction.DOWN, Direction.UP)
        )
        require(row != null) {
            "Could not find '${CompletionVsLastWorkoutStoreFixture.EXERCISE_NAME}' on completion screen."
        }

        val detectedStatus = readLastStatusForRow(row)
        require(detectedStatus == "ABOVE") {
            "Expected VS LAST to be ABOVE after editing reps, detected=${detectedStatus ?: "NONE"}"
        }
    }

    private fun seedPreviousCompletedHistory() = runBlocking {
        val db = AppDatabase.getDatabase(ApplicationProvider.getApplicationContext())
        db.workoutRecordDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutHistoryDao().deleteAll()

        val workoutHistoryId = UUID.fromString("45ddb966-b1c3-4d36-b296-64c57f38b37e")
        val workoutHistory = WorkoutHistory(
            id = workoutHistoryId,
            workoutId = CompletionVsLastWorkoutStoreFixture.WORKOUT_ID,
            date = LocalDate.of(2026, 3, 13),
            time = LocalTime.of(9, 0),
            startTime = LocalDateTime.of(2026, 3, 13, 8, 55),
            duration = 300,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = CompletionVsLastWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        )
        db.workoutHistoryDao().insert(workoutHistory)

        val setData = WeightSetData(
            actualReps = CompletionVsLastWorkoutStoreFixture.TEMPLATE_REPS,
            actualWeight = CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT,
            volume = CompletionVsLastWorkoutStoreFixture.TEMPLATE_REPS *
                CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT,
            subCategory = SetSubCategory.WorkSet
        )
        db.setHistoryDao().insert(
            SetHistory(
                id = UUID.fromString("63b3501c-5cdd-476b-bf5d-9d1f14f9f3a2"),
                workoutHistoryId = workoutHistoryId,
                exerciseId = CompletionVsLastWorkoutStoreFixture.EXERCISE_ID,
                setId = CompletionVsLastWorkoutStoreFixture.SET_ID,
                order = 0u,
                startTime = LocalDateTime.of(2026, 3, 13, 8, 55),
                endTime = LocalDateTime.of(2026, 3, 13, 8, 56),
                setData = setData,
                skipped = false,
                executionSequence = 0u
            )
        )
    }

    private fun modifyCurrentRepsByPlusOne(): Boolean {
        return WearWorkoutStateMutationHelper.incrementCurrentSetRepsByOne(device)
    }

    private fun readLastStatusForRow(labelNode: UiObject2): String? {
        var container: UiObject2? = labelNode
        repeat(4) {
            val status = container?.findObject(By.descStartsWith("LAST:"))
                ?.contentDescription
                ?.substringAfter("LAST:")
            if (!status.isNullOrBlank()) return status
            container = container?.parent
        }
        return null
    }
}
