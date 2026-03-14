package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID
import kotlin.math.abs

object CrossDeviceSyncAssertions {
    private const val HISTORY_RECENCY_MINUTES = 120L

    data class ExpectedSetSpec(
        val setId: UUID,
        val exerciseId: UUID,
        val order: Int,
        val expectedReps: Int,
        val expectedWeight: Double
    )

    data class Checkpoint(
        val label: String,
        val expectedSetIds: List<UUID>,
        val requiresCompletedHistory: Boolean,
        val requiresWorkoutRecord: Boolean
    )

    val expectedSetSpecsBySetId: Map<UUID, ExpectedSetSpec> = linkedMapOf(
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
            order = 0,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_EXPECTED_WEIGHT
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
            order = 2,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_EXPECTED_WEIGHT
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_B_ID,
            order = 0,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_EXPECTED_WEIGHT
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_C_ID,
            order = 0,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_EXPECTED_WEIGHT
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID,
            order = 0,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_EXPECTED_WEIGHT
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_ID to ExpectedSetSpec(
            setId = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_ID,
            exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID,
            order = 2,
            expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_EXPECTED_REPS,
            expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_EXPECTED_WEIGHT
        )
    )

    private val expectedExerciseSpecsByExerciseId: Map<UUID, List<ExpectedSetSpec>> = linkedMapOf(
        CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID to listOf(
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID),
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID)
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_B_ID to listOf(
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID)
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_C_ID to listOf(
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID)
        ),
        CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID to listOf(
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID),
            expectedSetSpecsBySetId.getValue(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_ID)
        )
    )

    val startedCheckpoint = Checkpoint(
        label = "workout-started",
        expectedSetIds = emptyList(),
        requiresCompletedHistory = false,
        requiresWorkoutRecord = true
    )

    val finalCheckpoint = Checkpoint(
        label = "workout-completed",
        expectedSetIds = expectedSetSpecsBySetId.keys.toList(),
        requiresCompletedHistory = true,
        requiresWorkoutRecord = false
    )

    val intermediateCheckpoints: List<Checkpoint> = listOf(
        startedCheckpoint,
        Checkpoint(
            label = "after-a1",
            expectedSetIds = listOf(CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID),
            requiresCompletedHistory = false,
            requiresWorkoutRecord = true
        ),
        Checkpoint(
            label = "after-a2",
            expectedSetIds = listOf(
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID
            ),
            requiresCompletedHistory = false,
            requiresWorkoutRecord = true
        ),
        Checkpoint(
            label = "after-b1",
            expectedSetIds = listOf(
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID
            ),
            requiresCompletedHistory = false,
            requiresWorkoutRecord = true
        ),
        Checkpoint(
            label = "after-c1",
            expectedSetIds = listOf(
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID
            ),
            requiresCompletedHistory = false,
            requiresWorkoutRecord = true
        ),
        Checkpoint(
            label = "after-d1",
            expectedSetIds = listOf(
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID,
                CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID
            ),
            requiresCompletedHistory = false,
            requiresWorkoutRecord = true
        ),
        finalCheckpoint
    )

    suspend fun waitForCheckpoint(
        context: Context,
        checkpoint: Checkpoint,
        timeoutMs: Long
    ) {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastFailure = "Checkpoint ${checkpoint.label} was not evaluated."

        while (System.currentTimeMillis() < deadline) {
            try {
                assertCheckpointState(db, checkpoint)
                return
            } catch (error: AssertionError) {
                lastFailure = error.message ?: error.toString()
            }
            delay(500)
        }

        throw AssertionError(
            "Checkpoint '${checkpoint.label}' did not materialize within ${timeoutMs}ms. Last failure: $lastFailure"
        )
    }

    suspend fun waitForFinalDerivedState(
        context: Context,
        timeoutMs: Long
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastFailure = "Final derived state was not evaluated."

        while (System.currentTimeMillis() < deadline) {
            try {
                assertFinalDerivedState(context)
                return
            } catch (error: AssertionError) {
                lastFailure = error.message ?: error.toString()
            }
            delay(500)
        }

        throw AssertionError(
            "Final derived phone state did not match within ${timeoutMs}ms. Last failure: $lastFailure"
        )
    }

    private suspend fun assertCheckpointState(
        db: AppDatabase,
        checkpoint: Checkpoint
    ) {
        val history = resolveHistory(
            db = db,
            requiresCompletedHistory = checkpoint.requiresCompletedHistory
        )
        val actualSetHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
        val expectedSpecs = checkpoint.expectedSetIds.map { expectedSetSpecsBySetId.getValue(it) }

        if (actualSetHistories.size != expectedSpecs.size) {
            fail(
                "Checkpoint ${checkpoint.label} expected ${expectedSpecs.size} set histories " +
                    "but found ${actualSetHistories.size} for history ${history.id}."
            )
        }

        val actualBySetId = actualSetHistories.associateBy { it.setId }
        if (actualBySetId.keys != expectedSpecs.map { it.setId }.toSet()) {
            fail(
                "Checkpoint ${checkpoint.label} set ids mismatch. " +
                    "expected=${expectedSpecs.map { it.setId }} actual=${actualBySetId.keys}"
            )
        }

        expectedSpecs.forEach { spec ->
            val actual = actualBySetId[spec.setId]
                ?: fail("Missing set history for setId=${spec.setId} at checkpoint ${checkpoint.label}.")
            assertSetHistoryMatches(
                actual = actual,
                expected = spec,
                label = "checkpoint=${checkpoint.label}",
                expectedWorkoutHistoryId = history.id
            )
        }

        val workoutRecord = db.workoutRecordDao()
            .getWorkoutRecordByWorkoutId(CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID)
        if (checkpoint.requiresWorkoutRecord) {
            if (workoutRecord == null) {
                fail("Checkpoint ${checkpoint.label} expected an active workout record.")
            }
            if (workoutRecord.workoutHistoryId != history.id) {
                fail(
                    "Checkpoint ${checkpoint.label} expected workoutRecord.workoutHistoryId=${history.id} " +
                        "but found ${workoutRecord.workoutHistoryId}."
                )
            }
        } else if (workoutRecord != null) {
            fail(
                "Checkpoint ${checkpoint.label} expected no active workout record, " +
                    "but found ${workoutRecord.id}."
            )
        }
    }

    private suspend fun assertFinalDerivedState(context: Context) {
        val db = AppDatabase.getDatabase(context)
        val history = resolveHistory(db = db, requiresCompletedHistory = true)
        val exerciseInfosById = db.exerciseInfoDao().getAllExerciseInfos().associateBy { it.id }

        expectedExerciseSpecsByExerciseId.forEach { (exerciseId, expectedSpecs) ->
            val exerciseInfo = exerciseInfosById[exerciseId]
                ?: fail("Missing ExerciseInfo for exerciseId=$exerciseId.")
            assertExerciseInfoMatches(
                exerciseInfo = exerciseInfo,
                expectedSpecs = expectedSpecs,
                workoutHistoryId = history.id
            )
        }

        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull {
            it.id == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID
        } ?: fail("Expected synced workout was not found in phone workout_store.json.")

        val exercisesById = workout.workoutComponents
            .filterIsInstance<Exercise>()
            .associateBy { it.id }

        expectedExerciseSpecsByExerciseId.forEach { (exerciseId, expectedSpecs) ->
            val exercise = exercisesById[exerciseId]
                ?: fail("Workout store is missing exerciseId=$exerciseId after final sync.")
            assertExerciseSetsMatch(exercise, expectedSpecs)
        }
    }

    private suspend fun resolveHistory(
        db: AppDatabase,
        requiresCompletedHistory: Boolean
    ): WorkoutHistory {
        val histories = db.workoutHistoryDao()
            .getAllWorkoutHistoriesByIsDone(requiresCompletedHistory)
            .filter {
                it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                    isHistoryRecent(it)
            }
            .sortedByDescending { it.version.toLong() }

        return histories.firstOrNull()
            ?: fail(
                "No ${if (requiresCompletedHistory) "completed" else "unfinished"} workout history " +
                    "found for workoutId=${CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID}."
            )
    }

    private fun assertExerciseInfoMatches(
        exerciseInfo: ExerciseInfo,
        expectedSpecs: List<ExpectedSetSpec>,
        workoutHistoryId: UUID
    ) {
        assertEmbeddedSetHistoryListMatches(
            actual = exerciseInfo.lastSuccessfulSession,
            expected = expectedSpecs,
            workoutHistoryId = workoutHistoryId,
            label = "ExerciseInfo.lastSuccessfulSession exerciseId=${exerciseInfo.id}"
        )
    }

    private fun assertEmbeddedSetHistoryListMatches(
        actual: List<SetHistory>,
        expected: List<ExpectedSetSpec>,
        workoutHistoryId: UUID,
        label: String
    ) {
        if (actual.size != expected.size) {
            fail("$label expected ${expected.size} sets but found ${actual.size}.")
        }

        actual.zip(expected).forEach { (actualSet, expectedSet) ->
            assertSetHistoryMatches(
                actual = actualSet,
                expected = expectedSet,
                label = label,
                expectedWorkoutHistoryId = workoutHistoryId
            )
        }
    }

    private fun assertExerciseSetsMatch(
        exercise: Exercise,
        expectedSpecs: List<ExpectedSetSpec>
    ) {
        val actualSets = exercise.sets
        if (actualSets.size != expectedSpecs.size) {
            fail(
                "Workout store exercise ${exercise.name} expected ${expectedSpecs.size} sets " +
                    "but found ${actualSets.size}."
            )
        }

        actualSets.zip(expectedSpecs).forEach { (actualSet, expectedSpec) ->
            val weightSet = actualSet as? WeightSet
                ?: fail("Workout store exercise ${exercise.name} contains a non-WeightSet for ${expectedSpec.setId}.")
            if (weightSet.id != expectedSpec.setId) {
                fail(
                    "Workout store exercise ${exercise.name} expected setId=${expectedSpec.setId} " +
                        "but found ${weightSet.id}."
                )
            }
            if (weightSet.reps != expectedSpec.expectedReps) {
                fail(
                    "Workout store exercise ${exercise.name} set ${weightSet.id} expected reps=" +
                        "${expectedSpec.expectedReps} but found ${weightSet.reps}."
                )
            }
            if (abs(weightSet.weight - expectedSpec.expectedWeight) >
                CrossDeviceSyncPhoneWorkoutStoreFixture.WEIGHT_TOLERANCE
            ) {
                fail(
                    "Workout store exercise ${exercise.name} set ${weightSet.id} expected weight=" +
                        "${expectedSpec.expectedWeight} but found ${weightSet.weight}."
                )
            }
        }
    }

    private fun assertSetHistoryMatches(
        actual: SetHistory,
        expected: ExpectedSetSpec,
        label: String,
        expectedWorkoutHistoryId: UUID
    ) {
        if (actual.workoutHistoryId != expectedWorkoutHistoryId) {
            fail(
                "$label expected workoutHistoryId=$expectedWorkoutHistoryId for setId=${expected.setId} " +
                    "but found ${actual.workoutHistoryId}."
            )
        }
        if (actual.exerciseId != expected.exerciseId) {
            fail(
                "$label expected exerciseId=${expected.exerciseId} for setId=${expected.setId} " +
                    "but found ${actual.exerciseId}."
            )
        }
        if (actual.order.toInt() != expected.order) {
            fail(
                "$label expected order=${expected.order} for setId=${expected.setId} " +
                    "but found ${actual.order}."
            )
        }
        if (actual.skipped) {
            fail("$label expected setId=${expected.setId} not to be skipped.")
        }

        val weightData = actual.setData as? WeightSetData
            ?: fail("$label expected WeightSetData for setId=${expected.setId}.")
        if (weightData.actualReps != expected.expectedReps) {
            fail(
                "$label expected reps=${expected.expectedReps} for setId=${expected.setId} " +
                    "but found ${weightData.actualReps}."
            )
        }
        if (abs(weightData.actualWeight - expected.expectedWeight) >
            CrossDeviceSyncPhoneWorkoutStoreFixture.WEIGHT_TOLERANCE
        ) {
            fail(
                "$label expected weight=${expected.expectedWeight} for setId=${expected.setId} " +
                    "but found ${weightData.actualWeight}."
            )
        }
    }

    private fun isHistoryRecent(workoutHistory: WorkoutHistory): Boolean {
        val ageMinutes = Duration.between(workoutHistory.startTime, LocalDateTime.now()).toMinutes()
        return ageMinutes in 0..HISTORY_RECENCY_MINUTES
    }

    private fun fail(message: String): Nothing = throw AssertionError(message)
}
