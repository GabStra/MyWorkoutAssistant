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
import com.gabstra.myworkoutassistant.shared.utils.Ternary
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
    private var scenario: CompletionVsLastScenario = CompletionVsLastScenario.Above

    override fun prepareAppStateBeforeLaunch() {
        CompletionVsLastWorkoutStoreFixture.setupWorkoutStore(
            context = context,
            setTemplates = scenario.workoutSetTemplates
        )
        seedPreviousCompletedHistory(scenario.historySetTemplates)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun completionProgression_marksVsLastAbove_whenSetIsEditedOnWear() {
        scenario = CompletionVsLastScenario.Above
        restartAppWithScenario()
        completeWorkoutForScenario(scenario)
        assertVsLastStatus(expected = Ternary.ABOVE)
    }

    @Test
    fun completionProgression_marksVsLastBelow_whenSetIsReducedOnWear() {
        scenario = CompletionVsLastScenario.Below
        restartAppWithScenario()
        completeWorkoutForScenario(scenario)
        assertVsLastStatus(expected = Ternary.BELOW)
    }

    @Test
    fun completionProgression_marksVsLastMixed_whenOneSetImprovesAndAnotherRegresses() {
        scenario = CompletionVsLastScenario.Mixed
        restartAppWithScenario()
        completeWorkoutForScenario(scenario)
        assertVsLastStatus(expected = Ternary.MIXED)
    }

    private fun restartAppWithScenario() {
        device.pressHome()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        device.executeShellCommand("am kill ${context.packageName}")
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        context.getSharedPreferences("workout_state", android.content.Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
        context.getSharedPreferences("workout_recovery_checkpoint", android.content.Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
        CompletionVsLastWorkoutStoreFixture.setupWorkoutStore(
            context = context,
            setTemplates = scenario.workoutSetTemplates
        )
        seedPreviousCompletedHistory(scenario.historySetTemplates)
        launchAppFromHome()
        workoutDriver = createWorkoutDriver()
    }

    private fun seedPreviousCompletedHistory(
        setTemplates: List<CompletionVsLastWorkoutStoreFixture.SetTemplate>
    ) = runBlocking {
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

        setTemplates.forEachIndexed { index, template ->
            val setData = WeightSetData(
                actualReps = template.reps,
                actualWeight = template.weight,
                volume = template.reps * template.weight,
                subCategory = SetSubCategory.WorkSet
            )
            db.setHistoryDao().insert(
                SetHistory(
                    id = UUID.nameUUIDFromBytes("completion-vs-last-history-$index".toByteArray()),
                    workoutHistoryId = workoutHistoryId,
                    exerciseId = CompletionVsLastWorkoutStoreFixture.EXERCISE_ID,
                    setId = template.id,
                    order = index.toUInt(),
                    startTime = LocalDateTime.of(2026, 3, 13, 8, 55).plusMinutes(index.toLong()),
                    endTime = LocalDateTime.of(2026, 3, 13, 8, 56).plusMinutes(index.toLong()),
                    setData = setData,
                    skipped = false,
                    executionSequence = index.toUInt()
                )
            )
        }
    }

    private fun completeWorkoutForScenario(scenario: CompletionVsLastScenario) {
        startWorkout(CompletionVsLastWorkoutStoreFixture.getWorkoutName())

        scenario.mutations.forEachIndexed { index, mutation ->
            val expectedSetId = scenario.workoutSetTemplates[index].id
            val currentSetReady = waitForCurrentSet(expectedSetId = expectedSetId)
            require(currentSetReady) {
                "Expected set ${index + 1} ($expectedSetId) was not ready before mutation."
            }

            val modified = WearWorkoutStateMutationHelper.updateCurrentWeightSet(
                device = device,
                actualReps = mutation.actualReps,
                actualWeight = mutation.actualWeight
            )
            require(modified) {
                "Failed to update set ${index + 1} before completing the workout."
            }

            val completed = WearWorkoutStateMutationHelper.completeCurrentSet(
                device = device,
                context = context,
                timeoutMs = 20_000
            )
            require(completed) {
                "Failed to complete set ${index + 1} while validating VS LAST."
            }
        }

        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
    }

    private fun waitForCurrentSet(expectedSetId: UUID, timeoutMs: Long = 10_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val currentSetId = WearWorkoutStateMutationHelper.getCurrentSetId()
            if (currentSetId == expectedSetId) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    private fun assertVsLastStatus(expected: Ternary) {
        val row = workoutDriver.findWithScrollFallback(
            selector = By.text(CompletionVsLastWorkoutStoreFixture.EXERCISE_NAME),
            initialWaitMs = 4_000,
            directions = listOf(Direction.DOWN, Direction.UP)
        )
        require(row != null) {
            "Could not find '${CompletionVsLastWorkoutStoreFixture.EXERCISE_NAME}' on completion screen."
        }

        val detectedStatus = readLastStatusForRow(row)
        require(detectedStatus == expected.name) {
            "Expected VS LAST to be ${expected.name}, detected=${detectedStatus ?: "NONE"}"
        }
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

    private data class SetMutation(
        val actualReps: Int,
        val actualWeight: Double
    )

    private sealed class CompletionVsLastScenario(
        val workoutSetTemplates: List<CompletionVsLastWorkoutStoreFixture.SetTemplate>,
        val historySetTemplates: List<CompletionVsLastWorkoutStoreFixture.SetTemplate>,
        val mutations: List<SetMutation>
    ) {
        data object Above : CompletionVsLastScenario(
            workoutSetTemplates = CompletionVsLastWorkoutStoreFixture.defaultTemplates,
            historySetTemplates = CompletionVsLastWorkoutStoreFixture.defaultTemplates,
            mutations = listOf(
                SetMutation(
                    actualReps = CompletionVsLastWorkoutStoreFixture.TEMPLATE_REPS + 1,
                    actualWeight = CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT
                )
            )
        )

        data object Below : CompletionVsLastScenario(
            workoutSetTemplates = CompletionVsLastWorkoutStoreFixture.defaultTemplates,
            historySetTemplates = CompletionVsLastWorkoutStoreFixture.defaultTemplates,
            mutations = listOf(
                SetMutation(
                    actualReps = CompletionVsLastWorkoutStoreFixture.TEMPLATE_REPS - 1,
                    actualWeight = CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT
                )
            )
        )

        data object Mixed : CompletionVsLastScenario(
            workoutSetTemplates = CompletionVsLastWorkoutStoreFixture.mixedTemplates,
            historySetTemplates = CompletionVsLastWorkoutStoreFixture.mixedTemplates,
            mutations = listOf(
                SetMutation(
                    actualReps = CompletionVsLastWorkoutStoreFixture.TEMPLATE_REPS + 1,
                    actualWeight = CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT
                ),
                SetMutation(
                    actualReps = CompletionVsLastWorkoutStoreFixture.SECOND_TEMPLATE_REPS - 1,
                    actualWeight = CompletionVsLastWorkoutStoreFixture.TEMPLATE_WEIGHT
                )
            )
        )
    }
}
