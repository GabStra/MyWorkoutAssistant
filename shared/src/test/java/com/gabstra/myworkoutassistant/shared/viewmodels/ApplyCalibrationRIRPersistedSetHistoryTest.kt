package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.time.LocalDateTime
import java.util.UUID
import kotlin.math.abs

/**
 * Ensures [WorkoutViewModel.applyCalibrationRIR] persists the calibration execution (with selected
 * [WeightSetData.calibrationRIR]) into [WorkoutViewModel.executedSetsHistory]. Requires the same
 * [androidx.compose.runtime.MutableState] for calibration Set execution and [WorkoutState.CalibrationRIRSelection]
 * as production ([WorkoutViewModel.completeCalibrationSet]).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class ApplyCalibrationRIRPersistedSetHistoryTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val calibrationSetId = UUID.randomUUID()
    private val workSetId = UUID.randomUUID()

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries().build()

        val tempDir = File(context.cacheDir, "test_workout_store_calibration_history")
        tempDir.mkdirs()
        val mockWorkoutStoreRepository = WorkoutStoreRepository(tempDir)

        viewModel = WorkoutViewModel(TestDispatcherProvider(testDispatcher))

        listOf(
            "setHistoryDao" to database.setHistoryDao(),
            "workoutHistoryDao" to database.workoutHistoryDao(),
            "workoutScheduleDao" to database.workoutScheduleDao(),
            "workoutRecordDao" to database.workoutRecordDao(),
            "exerciseInfoDao" to database.exerciseInfoDao(),
            "exerciseSessionProgressionDao" to database.exerciseSessionProgressionDao()
        ).forEach { (name, dao) ->
            val field = WorkoutViewModel::class.java.getDeclaredField(name)
            field.isAccessible = true
            field.set(viewModel, dao)
        }

        viewModel.initWorkoutStoreRepository(mockWorkoutStoreRepository)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    @Test
    fun applyCalibrationRIR_persistsCalibrationSetHistoryWithSelectedRir() = runTest(testDispatcher) {
        val calibrationWeight = 60.0
        val selectedRir = 3.0
        val initialWorkWeight = 50.0

        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(calibrationSetId, reps = 8, weight = calibrationWeight, subCategory = SetSubCategory.CalibrationSet),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSetId, reps = 8, weight = initialWorkWeight)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            requiresLoadCalibration = true
        )

        setSelectedWorkoutForTest(
            Workout(
                id = UUID.randomUUID(),
                name = "Workout",
                description = "",
                workoutComponents = listOf(workoutExercise),
                order = 0,
                enabled = true,
                creationDate = java.time.LocalDate.now(),
                type = 0,
                globalId = UUID.randomUUID()
            )
        )
        viewModel.initializeExercisesMaps(viewModel.selectedWorkout.value)

        val sharedCalibrationData = mutableStateOf<SetData>(
            WeightSetData(8, calibrationWeight, calibrationWeight * 8, subCategory = SetSubCategory.CalibrationSet)
        )

        val calibrationExecutionState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = calibrationWeight,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = sharedCalibrationData,
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = true
        )

        val calibrationRirState = WorkoutState.CalibrationRIRSelection(
            exerciseId = exerciseId,
            calibrationSet = calibrationExecutionState.set,
            setIndex = calibrationExecutionState.setIndex,
            currentSetDataState = sharedCalibrationData,
            equipmentId = null,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0
        )

        val workSetState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSetId, reps = 8, weight = initialWorkWeight),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWorkWeight, initialWorkWeight * 8)),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val postRirRest = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 60),
            order = 1u,
            currentSetDataState = mutableStateOf(RestSetData(60, 60)),
            exerciseId = exerciseId,
            nextState = workSetState,
            startTime = null,
            isIntraSetRest = false
        )

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.CalibrationExecutionBlock(
                            mutableListOf(calibrationExecutionState, calibrationRirState, postRirRest)
                        ),
                        ExerciseChildItem.Normal(workSetState)
                    )
                )
            )
        )

        val rirSelectionIndex = 1
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, rirSelectionIndex)
        viewModel.updateStateFlowsFromMachine()

        viewModel.applyCalibrationRIR(rir = selectedRir, formBreaks = false)
        advanceUntilIdle()

        val calibrationHistory = viewModel.executedSetsHistory.filter { it.setId == calibrationSetId }
        assertEquals("Expected one persisted calibration set history", 1, calibrationHistory.size)
        val sd = calibrationHistory.first().setData as WeightSetData
        assertEquals(SetSubCategory.CalibrationSet, sd.subCategory)
        assertNotNull(sd.calibrationRIR)
        assertTrue("calibrationRIR should match selected RIR", abs(sd.calibrationRIR!! - selectedRir) < 1e-9)
        assertTrue("actualWeight should match calibration load", abs(sd.actualWeight - calibrationWeight) < 1e-9)
    }

    private fun setSelectedWorkoutForTest(workout: Workout) {
        val selectedWorkoutField = WorkoutViewModel::class.java.getDeclaredField("_selectedWorkout")
        selectedWorkoutField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val selectedWorkoutState = selectedWorkoutField.get(viewModel) as androidx.compose.runtime.MutableState<Workout>
        selectedWorkoutState.value = workout
    }
}
