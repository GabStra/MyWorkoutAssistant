package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
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
import org.junit.Assert.assertFalse
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class ConfirmCalibrationLoadWarmupInsertionTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val equipmentId = UUID.randomUUID()

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries().build()

        val tempDir = File(context.cacheDir, "test_workout_store")
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
    fun createStatesFromExercise_beforeLoadConfirmation_hasNoCalibrationExecutionSet() = runTest(testDispatcher) {
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(UUID.randomUUID(), reps = 8, weight = 80.0)
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
            generateWarmUpSets = true,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            requiresLoadCalibration = true
        )

        val states = viewModel.createStatesFromExercise(exercise)
        assertTrue(
            "Calibration load selection should exist before confirmation",
            states.any { it is WorkoutState.CalibrationLoadSelection }
        )
        assertFalse(
            "Calibration execution set should not exist before load confirmation",
            states.any { it is WorkoutState.Set && it.isCalibrationSet }
        )
    }

    @Test
    fun confirmCalibrationLoad_createsExpectedStateOrderAfterPickingLoad() = runTest(testDispatcher) {
        val barbell = Barbell(
            id = equipmentId,
            name = "Test Barbell",
            availablePlates = listOf(
                Plate(20.0, 20.0),
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0),
                Plate(1.25, 3.0)
            ),
            sleeveLength = 200,
            barWeight = 20.0
        )

        val calibrationSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val selectedWeight = 100.0

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSetId, reps = 8, weight = 80.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = true,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            requiresLoadCalibration = true
        )
        viewModel.exercisesById = mapOf(exerciseId to exercise)

        val loadSelectionState = WorkoutState.CalibrationLoadSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, selectedWeight, selectedWeight * 8)),
            equipment = barbell,
            currentBodyWeight = 75.0
        )

        val workSetState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(id = workSetId, reps = 8, weight = 80.0),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val calibrationExecutionPlaceholder = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = true
        )

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.LoadSelectionBlock(mutableListOf(loadSelectionState)),
                        ExerciseChildItem.CalibrationExecutionBlock(mutableListOf(calibrationExecutionPlaceholder)),
                        ExerciseChildItem.Normal(workSetState)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)

        viewModel.confirmCalibrationLoad()
        advanceUntilIdle()

        val updatedMachine = viewModel.stateMachine
        assertTrue("State machine should be available", updatedMachine != null)
        val statesAfterConfirm = viewModel.getStatesForExercise(exerciseId)
            .filter { it !is WorkoutState.Rest }

        val firstState = statesAfterConfirm.firstOrNull() as? WorkoutState.CalibrationLoadSelection
        assertTrue("First state should remain calibration load selection", firstState != null)

        val calibrationStates = statesAfterConfirm
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.isCalibrationSet }
        assertEquals("Calibration execution should appear exactly once", 1, calibrationStates.size)

        val calibrationExecutionIndex = statesAfterConfirm.indexOfFirst {
            it is WorkoutState.Set && it.isCalibrationSet
        }
        val loadSelectionIndex = statesAfterConfirm.indexOfFirst { it is WorkoutState.CalibrationLoadSelection }
        assertTrue(
            "Calibration execution should be after load selection",
            calibrationExecutionIndex > loadSelectionIndex
        )

        val warmupIndices = statesAfterConfirm.mapIndexedNotNull { idx, state ->
            if (state is WorkoutState.Set && state.isWarmupSet) idx else null
        }
        if (warmupIndices.isNotEmpty()) {
            assertTrue(
                "Calibration execution should be after generated warmups",
                calibrationExecutionIndex > warmupIndices.max()
            )
        }

        val workSetIndex = statesAfterConfirm.indexOfFirst {
            it is WorkoutState.Set && !it.isWarmupSet && !it.isCalibrationSet && it.set.id == workSetId
        }
        assertTrue("Work set should come after calibration execution", workSetIndex > calibrationExecutionIndex)
    }

    @Test
    fun completeCalibrationSet_insertsRirStateAfterCalibrationExecution() = runTest(testDispatcher) {
        val barbell = Barbell(
            id = equipmentId,
            name = "Test Barbell",
            availablePlates = listOf(
                Plate(20.0, 20.0),
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0),
                Plate(1.25, 3.0)
            ),
            sleeveLength = 200,
            barWeight = 20.0
        )

        val calibrationSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val selectedWeight = 90.0

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(workSetId, reps = 8, weight = 80.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            requiresLoadCalibration = true
        )
        viewModel.exercisesById = mapOf(exerciseId to exercise)

        val loadSelectionState = WorkoutState.CalibrationLoadSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, selectedWeight, selectedWeight * 8)),
            equipment = barbell,
            currentBodyWeight = 75.0
        )

        val calibrationExecutionPlaceholder = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = true
        )

        val workSetState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(id = workSetId, reps = 8, weight = 80.0),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.LoadSelectionBlock(mutableListOf(loadSelectionState)),
                        ExerciseChildItem.CalibrationExecutionBlock(mutableListOf(calibrationExecutionPlaceholder)),
                        ExerciseChildItem.Normal(workSetState)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)

        viewModel.confirmCalibrationLoad()
        advanceUntilIdle()

        val machineAfterConfirm = viewModel.stateMachine
        assertNotNull("State machine should exist after confirming load", machineAfterConfirm)
        val calibrationExecutionIndex = machineAfterConfirm!!.allStates.indexOfFirst {
            it is WorkoutState.Set && it.isCalibrationSet && it.exerciseId == exerciseId
        }
        assertTrue("Calibration execution state should exist", calibrationExecutionIndex >= 0)

        viewModel.stateMachine = machineAfterConfirm.withCurrentIndex(calibrationExecutionIndex)
        viewModel.completeCalibrationSet()
        advanceUntilIdle()

        val machineAfterComplete = viewModel.stateMachine
        assertNotNull("State machine should exist after completing calibration set", machineAfterComplete)
        val exerciseStates = viewModel.getStatesForExercise(exerciseId)

        val calExecIdx = exerciseStates.indexOfFirst { it is WorkoutState.Set && it.isCalibrationSet }
        assertTrue("Calibration execution should exist in exercise states", calExecIdx >= 0)

        val nextState = exerciseStates.getOrNull(calExecIdx + 1)
        assertTrue("RIR state should be immediately after calibration execution", nextState is WorkoutState.CalibrationRIRSelection)

        val stateAfterRir = exerciseStates.getOrNull(calExecIdx + 2)
        assertTrue("Rest state should follow RIR state", stateAfterRir is WorkoutState.Rest)
    }

    @Test
    fun confirmCalibrationLoad_keepsCalibrationLoadSelectionStateWithSharedSetId() = runTest(testDispatcher) {
        val barbell = Barbell(
            id = equipmentId,
            name = "Test Barbell",
            availablePlates = listOf(
                Plate(20.0, 20.0),
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0),
                Plate(1.25, 3.0)
            ),
            sleeveLength = 200,
            barWeight = 20.0
        )

        val calibrationSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val selectedWeight = 95.0

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(workSetId, reps = 8, weight = 80.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            requiresLoadCalibration = true
        )
        viewModel.exercisesById = mapOf(exerciseId to exercise)

        val loadSelectionState = WorkoutState.CalibrationLoadSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, selectedWeight, selectedWeight * 8)),
            equipment = barbell,
            currentBodyWeight = 75.0
        )

        val calibrationExecutionPlaceholder = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = true
        )

        val workSetState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(id = workSetId, reps = 8, weight = 80.0),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.LoadSelectionBlock(mutableListOf(loadSelectionState)),
                        ExerciseChildItem.CalibrationExecutionBlock(mutableListOf(calibrationExecutionPlaceholder)),
                        ExerciseChildItem.Normal(workSetState)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)

        viewModel.confirmCalibrationLoad()
        advanceUntilIdle()

        val statesAfterConfirm = viewModel.getStatesForExercise(exerciseId)
        val loadSelections = statesAfterConfirm.filterIsInstance<WorkoutState.CalibrationLoadSelection>()
        val calibrationExecSets = statesAfterConfirm.filterIsInstance<WorkoutState.Set>()
            .filter { it.isCalibrationSet }

        assertEquals(
            "Exactly one CalibrationLoadSelection should remain after confirmation",
            1,
            loadSelections.size
        )
        assertEquals(
            "Exactly one calibration execution set should exist after confirmation",
            1,
            calibrationExecSets.size
        )
        assertTrue(
            "CalibrationLoadSelection and calibration execution set should share set.id without replacement collision",
            loadSelections.first().calibrationSet.id == calibrationExecSets.first().set.id
        )
    }
}
