package com.gabstra.myworkoutassistant.shared.viewmodels

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.datalayer.WatchWorkoutDefinitionEditIntent
import com.gabstra.myworkoutassistant.shared.datalayer.WatchWorkoutDefinitionEditKind
import com.gabstra.myworkoutassistant.shared.datalayer.WatchWorkoutDefinitionEditResult
import com.gabstra.myworkoutassistant.shared.datalayer.WatchWorkoutSetEdit
import com.gabstra.myworkoutassistant.shared.datalayer.WatchWorkoutSetKind
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class WatchWorkoutDefinitionPersistenceTest {

    @Test
    fun alreadyAppliedDefinitionEditStillSendsIntentForPhoneRetry() = runTest {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Workout",
            description = "",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Press",
                    notes = "",
                    sets = listOf(
                        WeightSet(
                            id = setId,
                            reps = 8,
                            weight = 90.0,
                            subCategory = SetSubCategory.WorkSet,
                        ),
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minReps = 5,
                    maxReps = 12,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = null,
                    bodyWeightPercentage = null,
                    progressionMode = ProgressionMode.OFF,
                    requiresLoadCalibration = false,
                ),
            ),
            order = 0,
            enabled = true,
            creationDate = LocalDate.now(),
            type = 0,
            globalId = UUID.randomUUID(),
        )
        val intent = WatchWorkoutDefinitionEditIntent(
            workoutId = workout.id,
            workoutGlobalId = workout.globalId,
            exerciseId = exerciseId,
            kind = WatchWorkoutDefinitionEditKind.LOAD_CALIBRATION,
            baseEquipmentId = null,
            baseRequiresLoadCalibration = true,
            setEdits = listOf(
                WatchWorkoutSetEdit(
                    setId = setId,
                    setKind = WatchWorkoutSetKind.WEIGHT,
                    baseWeight = 100.0,
                    newWeight = 90.0,
                    baseSubCategory = SetSubCategory.CalibrationPendingSet,
                    newSubCategory = SetSubCategory.WorkSet,
                ),
            ),
        )
        val viewModel = RecordingWorkoutViewModel(
            TestDispatcherProvider(StandardTestDispatcher(testScheduler)),
        )
        viewModel.workoutStore = WorkoutStore(
            workouts = listOf(workout),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0,
        )

        val result = viewModel.persistSelectedWorkoutDefinition(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.AlreadyApplied)
        assertEquals(listOf(intent), viewModel.changedIntents)
        assertTrue(viewModel.rejectedReasons.isEmpty())
    }

    private class RecordingWorkoutViewModel(
        dispatcherProvider: TestDispatcherProvider,
    ) : WorkoutViewModel(dispatcherProvider) {
        val changedIntents = mutableListOf<WatchWorkoutDefinitionEditIntent?>()
        val rejectedReasons = mutableListOf<String>()

        override suspend fun onWorkoutDefinitionChanged(
            updatedWorkoutStore: WorkoutStore,
            editIntent: WatchWorkoutDefinitionEditIntent?,
        ) {
            changedIntents += editIntent
        }

        override suspend fun onWorkoutDefinitionPersistRejected(reason: String) {
            rejectedReasons += reason
        }
    }
}
