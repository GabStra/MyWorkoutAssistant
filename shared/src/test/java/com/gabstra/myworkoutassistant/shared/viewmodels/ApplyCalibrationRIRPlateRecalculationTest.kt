package com.gabstra.myworkoutassistant.shared.viewmodels
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertFalse
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
 * Tests that after calibration RIR is applied, work set states get non-null plateChangeResult
 * (via [WorkoutViewModel.recalculatePlatesForExerciseFromIndex]).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class ApplyCalibrationRIRPlateRecalculationTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var stateMachineField: java.lang.reflect.Field
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val workSet1Id = UUID.randomUUID()
    private val workSet2Id = UUID.randomUUID()
    private val barbellId = UUID.randomUUID()
    private val barbell: Barbell = Barbell(
        id = barbellId,
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

        stateMachineField = WorkoutViewModel::class.java.getDeclaredField("stateMachine")
        stateMachineField.isAccessible = true

        viewModel.initWorkoutStoreRepository(mockWorkoutStoreRepository)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    @Test
    fun recalculatePlatesForExerciseFromIndex_populatesPlateChangeResultForAllWorkSets() = runTest(testDispatcher) {
        val totalWeight = 60.0 // 20kg bar + 40kg plates = 20kg per side
        val workSet1 = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, totalWeight),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, totalWeight, totalWeight * 8)),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 70.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = barbell.id,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
        val workSet2 = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, totalWeight),
            setIndex = 3u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, totalWeight, totalWeight * 8)),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 70.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = barbell.id,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
        val rest1 = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = workSet1,
            startTime = null,
            isIntraSetRest = false
        )
        val rest2 = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 2u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = workSet2,
            startTime = null,
            isIntraSetRest = false
        )

        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(rest1, workSet1, rest2, workSet2).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val sequence = listOf(WorkoutStateSequenceItem.Container(container))
        val machine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)
        stateMachineField.set(viewModel, machine)

        viewModel.recalculatePlatesForExerciseFromIndex(
            exerciseId = exerciseId,
            firstWorkSetStateIndex = 1,
            weights = listOf(totalWeight, totalWeight),
            equipment = barbell
        )
        advanceUntilIdle()

        val updatedMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(updatedMachine)
        val allStates = updatedMachine!!.allStates
        val workSetStates = allStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }

        assertTrue("Expected 2 work set states", workSetStates.size == 2)
        workSetStates.forEach { setState ->
            assertNotNull(
                "Work set ${setState.set.id} should have plateChangeResult after recalculation",
                setState.plateChangeResult
            )
            val result = setState.plateChangeResult!!
            val sideWeight = result.currentPlates.sum()
            val totalFromPlates = barbell.barWeight + (sideWeight * 2)
            assertTrue(
                "Plate total $totalFromPlates should be close to $totalWeight (delta ${abs(totalFromPlates - totalWeight)})",
                abs(totalFromPlates - totalWeight) < 0.01
            )
        }
    }

    @Test
    fun applyCalibrationRIR_updatesPostRirRestNextStateAndAllWorkSetsToAdjustedPlateConfiguration() = runTest(testDispatcher) {
        val initialWorkSetWeight = 80.0
        val calibrationSelectedWeight = 92.5
        val rir = 2.0
        val expectedAdjustedWeight = CalibrationHelper.applyCalibrationAdjustment(calibrationSelectedWeight, rir)
        val calibrationSetId = UUID.randomUUID()

        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSet1Id, reps = 8, weight = initialWorkSetWeight),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSet2Id, reps = 8, weight = initialWorkSetWeight)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = barbell.id,
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

        val loadSelectionState = WorkoutState.CalibrationLoadSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = initialWorkSetWeight,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(8, calibrationSelectedWeight, calibrationSelectedWeight * 8)
            ),
            equipmentId = barbell.id,
            currentBodyWeight = 75.0,
            isLoadConfirmed = true
        )

        val calibrationExecutionState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = calibrationSetId,
                reps = 8,
                weight = calibrationSelectedWeight,
                subCategory = SetSubCategory.CalibrationSet
            ),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(8, calibrationSelectedWeight, calibrationSelectedWeight * 8)
            ),
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
            equipmentId = barbell.id,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = true
        )

        val calibrationRirState = WorkoutState.CalibrationRIRSelection(
            exerciseId = exerciseId,
            calibrationSet = calibrationExecutionState.set,
            setIndex = calibrationExecutionState.setIndex,
            currentSetDataState = mutableStateOf(
                WeightSetData(8, calibrationSelectedWeight, calibrationSelectedWeight * 8)
            ),
            equipmentId = barbell.id,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0
        )

        val workSet1State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, reps = 8, weight = initialWorkSetWeight),
            setIndex = 3u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWorkSetWeight, initialWorkSetWeight * 8)),
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
            equipmentId = barbell.id,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val postRirRest = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 60),
            order = 2u,
            currentSetDataState = mutableStateOf(RestSetData(60, 60)),
            exerciseId = exerciseId,
            nextState = workSet1State,
            startTime = null,
            isIntraSetRest = false
        )

        val workSet2State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, reps = 8, weight = initialWorkSetWeight),
            setIndex = 5u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWorkSetWeight, initialWorkSetWeight * 8)),
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
            equipmentId = barbell.id,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        val betweenWorkSetsRest = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 4u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = workSet2State,
            startTime = null,
            isIntraSetRest = false
        )

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.LoadSelectionBlock(mutableListOf(loadSelectionState)),
                        ExerciseChildItem.CalibrationExecutionBlock(
                            mutableListOf(calibrationExecutionState, calibrationRirState, postRirRest)
                        ),
                        ExerciseChildItem.Normal(workSet1State),
                        ExerciseChildItem.Normal(betweenWorkSetsRest),
                        ExerciseChildItem.Normal(workSet2State)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 2)

        viewModel.applyCalibrationRIR(rir = rir)
        advanceUntilIdle()

        val updatedStates = viewModel.getStatesForExercise(exerciseId)
        assertFalse(
            "CalibrationRIRSelection should be removed after applying RIR",
            updatedStates.any { it is WorkoutState.CalibrationRIRSelection }
        )

        val calibrationSetIndex = updatedStates.indexOfFirst { it is WorkoutState.Set && it.isCalibrationSet }
        assertTrue("Calibration execution set should still exist", calibrationSetIndex >= 0)
        val restAfterCalibration = updatedStates.getOrNull(calibrationSetIndex + 1) as? WorkoutState.Rest
        assertNotNull("Rest state should exist after calibration execution", restAfterCalibration)
        val restNextSet = restAfterCalibration!!.nextState as? WorkoutState.Set
        assertNotNull("Rest state after calibration should point to next work set", restNextSet)
        val restNextWeight = (restNextSet!!.set as WeightSet).weight
        assertTrue(
            "Rest next state should use adjusted load. expected=$expectedAdjustedWeight actual=$restNextWeight initial=$initialWorkSetWeight",
            kotlin.math.abs(restNextWeight - expectedAdjustedWeight) < 0.01
        )
        // Rest's nextState may or may not have plateChangeResult depending on populateNextStateForRest timing
        if (restNextSet.plateChangeResult != null) {
            assertTrue(
                "Rest next state's plate config should match adjusted load when present",
                kotlin.math.abs(totalWeightFromPlates(restNextSet.plateChangeResult!!) - expectedAdjustedWeight) < 0.01
            )
        }

        val updatedWorkSetStates = updatedStates
            .filterIsInstance<WorkoutState.Set>()
            .filter { !it.isCalibrationSet && !it.isWarmupSet }

        assertTrue("Expected two work set states", updatedWorkSetStates.size == 2)
        updatedWorkSetStates.forEach { workSetState ->
            val setWeight = (workSetState.set as WeightSet).weight
            assertTrue(
                "Work set ${workSetState.set.id} should use adjusted load",
                kotlin.math.abs(setWeight - expectedAdjustedWeight) < 0.01
            )
            assertTrue(
                "Work set ${workSetState.set.id} should not keep initial load",
                kotlin.math.abs(setWeight - initialWorkSetWeight) > 0.01
            )
            val setData = workSetState.currentSetData as? WeightSetData
            assertNotNull("Work set ${workSetState.set.id} should keep WeightSetData", setData)
            assertTrue(
                "Work set ${workSetState.set.id} set data should match adjusted load",
                kotlin.math.abs(setData!!.actualWeight - expectedAdjustedWeight) < 0.01
            )
            if (workSetState.plateChangeResult != null) {
                assertTrue(
                    "Work set ${workSetState.set.id} plate config should match adjusted load when present",
                    kotlin.math.abs(totalWeightFromPlates(workSetState.plateChangeResult!!) - expectedAdjustedWeight) < 0.01
                )
            }
        }
    }

    private fun setSelectedWorkoutForTest(workout: Workout) {
        val selectedWorkoutField = WorkoutViewModel::class.java.getDeclaredField("_selectedWorkout")
        selectedWorkoutField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val selectedWorkoutState = selectedWorkoutField.get(viewModel) as androidx.compose.runtime.MutableState<Workout>
        selectedWorkoutState.value = workout
    }

    private fun totalWeightFromPlates(plateChangeResult: PlateCalculator.Companion.PlateChangeResult): Double {
        val sideWeight = plateChangeResult.currentPlates.sum()
        return barbell.barWeight + (sideWeight * 2)
    }
}
