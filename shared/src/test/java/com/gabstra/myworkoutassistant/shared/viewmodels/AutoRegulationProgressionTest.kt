package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
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
import com.gabstra.myworkoutassistant.shared.workout.rir.applyAutoRegulationRIR
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
import kotlin.math.abs

/**
 * Unit tests for auto-regulation progression: state build (isAutoRegulationWorkSet),
 * completeAutoRegulationSet (below/in/above rep range), and applyAutoRegulationRIR.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class AutoRegulationProgressionTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var stateMachineField: java.lang.reflect.Field
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val workSet1Id = UUID.randomUUID()
    private val workSet2Id = UUID.randomUUID()
    private val barbellId = UUID.randomUUID()
    private val barbell = Barbell(
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

        viewModel.updateWorkoutStore(
            WorkoutStore(
                workouts = emptyList(),
                equipments = listOf(barbell),
                accessoryEquipments = emptyList(),
                workoutPlans = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                progressionPercentageAmount = 0.0,
                measuredMaxHeartRate = null,
                restingHeartRate = null
            )
        )
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    private fun setSelectedWorkoutForTest(workout: Workout) {
        val field = WorkoutViewModel::class.java.getDeclaredField("_selectedWorkout")
        field.isAccessible = true
        field.set(viewModel, androidx.compose.runtime.mutableStateOf(workout))
    }

    private fun nearestAvailableWeight(target: Double): Double {
        return barbell.getWeightsCombinations().minByOrNull { abs(it - target) } ?: target
    }

    @Test
    fun applyAutoRegulationRIR_removesAutoRegulationRIRSelectionAndStoresRIRAndUpdatesOnlySubsequentSets() = runTest(testDispatcher) {
        val initialWeight = 80.0
        val rir = 2.0
        val expectedAdjustedWeight = CalibrationHelper.applyCalibrationAdjustment(initialWeight, rir)

        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSet1Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSet2Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet)
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
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = false
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "W",
            description = "",
            workoutComponents = listOf(workoutExercise),
            order = 0,
            enabled = true,
            creationDate = java.time.LocalDate.now(),
            type = 0,
            globalId = UUID.randomUUID()
        )
        setSelectedWorkoutForTest(workout)
        viewModel.updateWorkoutStore(
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(barbell),
                accessoryEquipments = emptyList(),
                workoutPlans = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                progressionPercentageAmount = 0.0,
                measuredMaxHeartRate = null,
                restingHeartRate = null
            )
        )
        viewModel.initializeExercisesMaps(workout)

        val workSet1Data = WeightSetData(8, initialWeight, initialWeight * 8)
        val workSet2Data = WeightSetData(8, initialWeight, initialWeight * 8)

        val workSet1State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(workSet1Data),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = true
        )

        val autoRegRIRState = WorkoutState.AutoRegulationRIRSelection(
            exerciseId = exerciseId,
            workSet = workSet1State.set,
            setIndex = 0u,
            currentSetDataState = mutableStateOf(workSet1Data),
            equipmentId = barbell.id,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0
        )

        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 1u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )

        val workSet2State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(workSet2Data),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = false
        )
        restState.nextState = workSet2State

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.Normal(workSet1State),
                        ExerciseChildItem.Normal(autoRegRIRState),
                        ExerciseChildItem.Normal(restState),
                        ExerciseChildItem.Normal(workSet2State)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 1)

        val exercisesByIdField = WorkoutViewModel::class.java.getDeclaredField("exercisesById")
        exercisesByIdField.isAccessible = true
        exercisesByIdField.set(viewModel, mapOf(exerciseId to workoutExercise))

        viewModel.applyAutoRegulationRIR(rir = rir)
        advanceUntilIdle()

        val updatedStates = viewModel.getStatesForExercise(exerciseId)
        assertFalse(
            "AutoRegulationRIRSelection should be removed after applying RIR",
            updatedStates.any { it is WorkoutState.AutoRegulationRIRSelection }
        )

        val setStates = updatedStates.filterIsInstance<WorkoutState.Set>().filter { !it.isWarmupSet }
        assertEquals(2, setStates.size)
        val firstSetData = setStates[0].currentSetData as? WeightSetData
        assertNotNull(firstSetData)
        assertEquals(2.0, firstSetData!!.autoRegulationRIR!!, 0.01)

        val secondSet = setStates[1].set as? WeightSet
        assertNotNull(secondSet)
        assertTrue(
            "Subsequent set weight should be adjusted. expected=$expectedAdjustedWeight actual=${secondSet!!.weight}",
            abs(secondSet.weight - expectedAdjustedWeight) < 0.01
        )
    }

    @Test
    fun completeAutoRegulationSet_repsInRange_advancesWithoutRIRSelectionAndKeepsLoad() = runTest(testDispatcher) {
        val initialWeight = 80.0
        val expectedWeight = nearestAvailableWeight(initialWeight)
        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSet1Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSet2Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet)
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
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = false
        )
        setSelectedWorkoutForTest(
            Workout(
                id = UUID.randomUUID(),
                name = "W",
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

        val workSet1Data = WeightSetData(actualReps = 8, actualWeight = initialWeight, volume = initialWeight * 8)
        val workSet1State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(workSet1Data),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = true
        )

        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 1u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )

        val workSet2State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWeight, initialWeight * 8)),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = false
        )
        restState.nextState = workSet2State

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.Normal(workSet1State),
                        ExerciseChildItem.Normal(restState),
                        ExerciseChildItem.Normal(workSet2State)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)

        viewModel.completeAutoRegulationSet()
        advanceUntilIdle()

        val machine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(machine)
        assertFalse(
            "Current state should not be AutoRegulationRIRSelection when reps are in range",
            machine!!.currentState is WorkoutState.AutoRegulationRIRSelection
        )
        assertTrue(
            "Should advance after completing set. Actual: ${machine.currentState?.javaClass?.simpleName}",
            machine.currentState is WorkoutState.Rest || machine.currentState is WorkoutState.Set
        )

        val states = viewModel.getStatesForExercise(exerciseId)
        val firstSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet1Id }
        assertNotNull(firstSetState)
        val firstSetData = firstSetState!!.currentSetData as? WeightSetData
        assertNotNull(firstSetData)
        assertEquals(2.0, firstSetData!!.autoRegulationRIR!!, 0.01)

        val secondSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet2Id }
        assertNotNull(secondSetState)
        val secondSet = secondSetState!!.set as? WeightSet
        assertNotNull(secondSet)
        assertTrue(
            "Subsequent set weight should stay unchanged. expected=$expectedWeight actual=${secondSet!!.weight}",
            abs(secondSet.weight - expectedWeight) < 0.01
        )
    }

    @Test
    fun completeAutoRegulationSet_repsBelowRange_advancesAndStoresRIR0() = runTest(testDispatcher) {
        val initialWeight = 80.0
        val expectedAdjustedWeight = nearestAvailableWeight(initialWeight * 0.90)
        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSet1Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSet2Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet)
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
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = false
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "W",
            description = "",
            workoutComponents = listOf(workoutExercise),
            order = 0,
            enabled = true,
            creationDate = java.time.LocalDate.now(),
            type = 0,
            globalId = UUID.randomUUID()
        )
        setSelectedWorkoutForTest(workout)
        viewModel.updateWorkoutStore(
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(barbell),
                accessoryEquipments = emptyList(),
                workoutPlans = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                progressionPercentageAmount = 0.0,
                measuredMaxHeartRate = null,
                restingHeartRate = null
            )
        )
        viewModel.initializeExercisesMaps(workout)

        val workSet1Data = WeightSetData(actualReps = 3, actualWeight = initialWeight, volume = initialWeight * 3)
        val workSet1State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(workSet1Data),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = true
        )

        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 1u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )

        val workSet2State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWeight, initialWeight * 8)),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = false
        )
        restState.nextState = workSet2State

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.Normal(workSet1State),
                        ExerciseChildItem.Normal(restState),
                        ExerciseChildItem.Normal(workSet2State)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)
        viewModel.updateStateFlowsFromMachine()

        val exercisesByIdField = WorkoutViewModel::class.java.getDeclaredField("exercisesById")
        exercisesByIdField.isAccessible = true
        exercisesByIdField.set(viewModel, mapOf(exerciseId to workoutExercise))

        viewModel.completeAutoRegulationSet()
        advanceUntilIdle()

        val machine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(machine)
        assertFalse(
            "Current state should not be AutoRegulationRIRSelection when reps below range",
            machine!!.currentState is WorkoutState.AutoRegulationRIRSelection
        )
        assertTrue(
            "Should advance to Rest after completing set. Actual: ${machine.currentState?.javaClass?.simpleName}",
            machine.currentState is WorkoutState.Rest
        )

        val states = viewModel.getStatesForExercise(exerciseId)
        val firstSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet1Id }
        assertNotNull(firstSetState)
        val firstSetData = firstSetState!!.currentSetData as? WeightSetData
        assertNotNull(firstSetData)
        assertEquals(0.0, firstSetData!!.autoRegulationRIR!!, 0.01)

        val secondSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet2Id }
        assertNotNull(secondSetState)
        val secondSet = secondSetState!!.set as? WeightSet
        assertNotNull(secondSet)
        assertTrue(
            "Subsequent set weight should be decreased by 10% (rounded). expected=$expectedAdjustedWeight actual=${secondSet!!.weight}",
            abs(secondSet.weight - expectedAdjustedWeight) < 0.01
        )
    }

    @Test
    fun completeAutoRegulationSet_repsAboveRange_advancesAndStoresRIR3AndAdjustsSubsequentSet() = runTest(testDispatcher) {
        val initialWeight = 80.0
        val expectedAdjustedWeight = nearestAvailableWeight(initialWeight * 1.025)
        val workoutExercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(workSet1Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(workSet2Id, reps = 8, weight = initialWeight, subCategory = SetSubCategory.WorkSet)
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
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = false
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "W",
            description = "",
            workoutComponents = listOf(workoutExercise),
            order = 0,
            enabled = true,
            creationDate = java.time.LocalDate.now(),
            type = 0,
            globalId = UUID.randomUUID()
        )
        setSelectedWorkoutForTest(workout)
        viewModel.updateWorkoutStore(
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(barbell),
                accessoryEquipments = emptyList(),
                workoutPlans = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                progressionPercentageAmount = 0.0,
                measuredMaxHeartRate = null,
                restingHeartRate = null
            )
        )
        viewModel.initializeExercisesMaps(workout)

        val workSet1Data = WeightSetData(actualReps = 14, actualWeight = initialWeight, volume = initialWeight * 14)
        val workSet1State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(workSet1Data),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = true
        )

        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 1u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )

        val workSet2State = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, initialWeight, subCategory = SetSubCategory.WorkSet),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, initialWeight, initialWeight * 8)),
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
            isCalibrationSet = false,
            isAutoRegulationWorkSet = false
        )
        restState.nextState = workSet2State

        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.Normal(workSet1State),
                        ExerciseChildItem.Normal(restState),
                        ExerciseChildItem.Normal(workSet2State)
                    )
                )
            )
        )
        viewModel.stateMachine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)
        viewModel.updateStateFlowsFromMachine()

        val exercisesByIdField = WorkoutViewModel::class.java.getDeclaredField("exercisesById")
        exercisesByIdField.isAccessible = true
        exercisesByIdField.set(viewModel, mapOf(exerciseId to workoutExercise))

        viewModel.completeAutoRegulationSet()
        advanceUntilIdle()

        val machine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(machine)
        assertFalse(
            "Current state should not be AutoRegulationRIRSelection when reps are above range",
            machine!!.currentState is WorkoutState.AutoRegulationRIRSelection
        )
        assertTrue(
            "Should advance to Rest after completing set. Actual: ${machine.currentState?.javaClass?.simpleName}",
            machine.currentState is WorkoutState.Rest
        )

        val states = viewModel.getStatesForExercise(exerciseId)
        val firstSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet1Id }
        assertNotNull(firstSetState)
        val firstSetData = firstSetState!!.currentSetData as? WeightSetData
        assertNotNull(firstSetData)
        assertEquals(3.0, firstSetData!!.autoRegulationRIR!!, 0.01)

        val secondSetState = states.filterIsInstance<WorkoutState.Set>().firstOrNull { it.set.id == workSet2Id }
        assertNotNull(secondSetState)
        val secondSet = secondSetState!!.set as? WeightSet
        assertNotNull(secondSet)
        assertTrue(
            "Subsequent set weight should be adjusted. expected=$expectedAdjustedWeight actual=${secondSet!!.weight}",
            abs(secondSet.weight - expectedAdjustedWeight) < 0.01
        )
        assertNotNull(
            "Subsequent set plate change should be recalculated after auto-regulation adjustment",
            secondSetState.plateChangeResult
        )

        val currentRest = machine.currentState as? WorkoutState.Rest
        assertNotNull("Current state should be Rest after completion", currentRest)
        val nextSetFromRest = currentRest!!.nextState as? WorkoutState.Set
        assertNotNull("Rest nextState should point to the next set", nextSetFromRest)
        assertNotNull(
            "Rest nextState should include recalculated plate change",
            nextSetFromRest!!.plateChangeResult
        )
    }
}
